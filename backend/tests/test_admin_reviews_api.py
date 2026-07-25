"""管理员审核、发布、审计和用户越权回归。"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.admin_reviews import get_review_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import (
    AuditEvent,
    KnowledgeDocument,
    KnowledgeSubmission,
    ProcessingJob,
)
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.tokens import get_token_service
from app.modules.jobs.service import SqlAlchemyJobService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.repository import SubmissionReviewRepository
from app.modules.knowledge.review_service import KnowledgeReviewService
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_document_service import FakeVectorStore


class FailPublishedAudit:
    def record(self, event):
        if event.action == "knowledge_submission.published":
            raise RuntimeError("模拟最终审计写入失败")


def add_submission(factory, settings, submitter_id, suffix):
    settings.submission_dir.mkdir(parents=True, exist_ok=True)
    submission_id = f"review-{suffix}"
    stored_name = f"{submission_id}.txt"
    (settings.submission_dir / stored_name).write_text(
        f"审核资料{suffix}", encoding="utf-8"
    )
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id=submission_id,
                submitter_id=submitter_id,
                original_name=f"审核资料{suffix}.txt",
                stored_name=stored_name,
                content_hash=(suffix[0] * 64),
                size_bytes=20,
                status="pending_review",
                preview_text=f"预览{suffix}",
                preview_pages=1,
                parse_warnings=[],
            )
        )
        session.commit()
    return submission_id


def test_admin_can_reject_or_publish_and_normal_user_cannot_review(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'reviews.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "review-submitter")
    normal = create_test_user(factory, "review-normal")
    admin = create_test_user(factory, "review-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    rejected_id = add_submission(factory, settings, submitter.id, "a")
    approved_id = add_submission(factory, settings, submitter.id, "b")
    vectors = FakeVectorStore()

    def override_session():
        with factory() as session:
            yield session

    def override_review_service():
        with factory() as session:
            yield KnowledgeReviewService(
                session,
                settings,
                DocumentLifecycleService(session, settings, vectors),
                SqlAlchemyAuditRecorder(session),
                SqlAlchemyJobService(session),
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_review_service] = override_review_service
    try:
        with TestClient(app) as client:
            assert client.get(
                "/api/v1/admin/reviews",
                headers=auth_headers(normal.id),
            ).status_code == 403

            listed = client.get(
                "/api/v1/admin/reviews",
                headers=auth_headers(admin.id),
            )
            assert listed.status_code == 200
            assert listed.json()["total"] == 2
            assert listed.json()["items"][0]["preview_text"]

            rejected = client.post(
                f"/api/v1/admin/reviews/{rejected_id}/reject",
                json={"reason": "资料来源无法核验"},
                headers=auth_headers(admin.id),
            )
            assert rejected.status_code == 200
            assert rejected.json()["submission"]["status"] == "rejected"

            approved = client.post(
                f"/api/v1/admin/reviews/{approved_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code == 200
            assert approved.json()["submission"]["status"] == "published"
            assert approved.json()["job_id"]

        with factory() as session:
            published = session.get(KnowledgeSubmission, approved_id)
            assert published.document_id is not None
            assert session.get(KnowledgeDocument, published.document_id) is not None
            job = session.scalar(
                select(ProcessingJob).where(ProcessingJob.object_id == approved_id)
            )
            assert job.status == "completed" and job.progress == 100
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert actions == {
                "knowledge_submission.rejected",
                "knowledge_submission.published",
            }
        assert vectors.entries
        assert not (settings.submission_dir / f"{approved_id}.txt").exists()
        assert (settings.submission_dir / f"{rejected_id}.txt").exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_publish_finalization_failure_compensates_document_file_and_vectors(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-failure.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "failure-submitter")
    admin = create_test_user(factory, "failure-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    submission_id = add_submission(factory, settings, submitter.id, "c")
    vectors = FakeVectorStore()

    def override_session():
        with factory() as session:
            yield session

    def override_review_service():
        with factory() as session:
            yield KnowledgeReviewService(
                session,
                settings,
                DocumentLifecycleService(session, settings, vectors),
                FailPublishedAudit(),
                SqlAlchemyJobService(session),
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_review_service] = override_review_service
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert response.status_code == 500
            assert response.json()["error"]["code"] == "DOCUMENT_STORE_ERROR"

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            assert submission.status == "failed"
            assert submission.document_id is None
            assert session.scalar(select(KnowledgeDocument)) is None
            job = session.scalar(select(ProcessingJob))
            assert job.status == "failed"
        assert vectors.entries == {}
        assert not list(settings.upload_dir.glob("*"))
        assert (settings.submission_dir / f"{submission_id}.txt").exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_review_state_claim_allows_only_one_stale_reviewer(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-race.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "race-submitter")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")
    submission_id = add_submission(factory, settings, submitter.id, "d")

    first_session = factory()
    second_session = factory()
    try:
        assert first_session.get(KnowledgeSubmission, submission_id).status == "pending_review"
        assert second_session.get(KnowledgeSubmission, submission_id).status == "pending_review"

        assert SubmissionReviewRepository(first_session).claim_for_indexing(
            submission_id, "pending_review"
        )
        first_session.commit()
        assert not SubmissionReviewRepository(second_session).claim_for_indexing(
            submission_id, "pending_review"
        )
        second_session.rollback()
        assert not SubmissionReviewRepository(second_session).reject_pending(
            submission_id, "迟到的拒绝"
        )
    finally:
        first_session.close()
        second_session.close()
        engine.dispose()


def test_isolation_cleanup_failure_keeps_published_document_and_records_warning(
    tmp_path, monkeypatch
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'cleanup-warning.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "cleanup-submitter")
    admin = create_test_user(factory, "cleanup-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    submission_id = add_submission(factory, settings, submitter.id, "e")
    isolated_path = settings.submission_dir / f"{submission_id}.txt"
    vectors = FakeVectorStore()
    original_unlink = Path.unlink

    def fail_only_isolation_cleanup(path, *args, **kwargs):
        if path == isolated_path:
            raise OSError("模拟隔离文件清理失败")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_only_isolation_cleanup)

    def override_session():
        with factory() as session:
            yield session

    def override_review_service():
        with factory() as session:
            yield KnowledgeReviewService(
                session,
                settings,
                DocumentLifecycleService(session, settings, vectors),
                SqlAlchemyAuditRecorder(session),
                SqlAlchemyJobService(session),
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_review_service] = override_review_service
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert response.status_code == 200
            assert response.json()["submission"]["status"] == "published"

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            assert submission.status == "published"
            assert session.get(KnowledgeDocument, submission.document_id) is not None
            job = session.scalar(
                select(ProcessingJob).where(ProcessingJob.object_id == submission_id)
            )
            assert job.status == "completed"
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert {
                "knowledge_submission.published",
                "knowledge_submission.cleanup_pending",
            }.issubset(actions)
        assert isolated_path.exists()
        assert vectors.entries
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
