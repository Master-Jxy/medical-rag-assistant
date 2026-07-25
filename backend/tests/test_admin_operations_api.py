"""任务、审计范围和失败发布重试回归。"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.admin_reviews import get_review_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import AuditEvent, KnowledgeSubmission, ProcessingJob
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.tokens import get_token_service
from app.modules.jobs.service import SqlAlchemyJobService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.review_service import KnowledgeReviewService
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_document_service import FakeVectorStore


def test_job_retry_and_role_scoped_audit_queries(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'operations.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "operations-submitter")
    normal = create_test_user(factory, "operations-normal")
    admin = create_test_user(factory, "operations-admin", role="admin")
    owner = create_test_user(factory, "operations-owner", role="super_admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    settings.submission_dir.mkdir(parents=True)
    (settings.submission_dir / "failed.txt").write_text(
        "可以重试的资料", encoding="utf-8"
    )
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id="failed-submission",
                submitter_id=submitter.id,
                original_name="失败资料.txt",
                stored_name="failed.txt",
                content_hash="f" * 64,
                size_bytes=20,
                status="failed",
                failure_reason="RuntimeError",
                preview_text="预览",
                preview_pages=1,
                parse_warnings=[],
            )
        )
        session.add(
            ProcessingJob(
                id="failed-job",
                job_type="publish_submission",
                object_type="knowledge_submission",
                object_id="failed-submission",
                status="failed",
                progress=10,
                attempt_count=1,
                error_type="RuntimeError",
            )
        )
        session.add_all(
            [
                AuditEvent(
                    actor_user_id=owner.id,
                    action="user.role_changed",
                    object_type="user",
                    object_id=normal.id,
                    result="success",
                    details={},
                ),
                AuditEvent(
                    actor_user_id=admin.id,
                    action="knowledge_submission.rejected",
                    object_type="knowledge_submission",
                    object_id="other",
                    result="success",
                    details={},
                ),
            ]
        )
        session.commit()
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
                "/api/v1/admin/jobs",
                headers=auth_headers(normal.id),
            ).status_code == 403
            jobs = client.get(
                "/api/v1/admin/jobs?status=failed",
                headers=auth_headers(admin.id),
            )
            assert jobs.status_code == 200
            assert jobs.json()["total"] == 1
            assert jobs.json()["items"][0]["error_type"] == "RuntimeError"

            admin_audit = client.get(
                "/api/v1/admin/audit",
                headers=auth_headers(admin.id),
            )
            assert admin_audit.json()["total"] == 1
            assert admin_audit.json()["items"][0]["action"].startswith("knowledge_")

            owner_audit = client.get(
                "/api/v1/admin/audit",
                headers=auth_headers(owner.id),
            )
            assert owner_audit.json()["total"] == 2

            retried = client.post(
                "/api/v1/admin/jobs/failed-job/retry",
                headers=auth_headers(admin.id),
            )
            assert retried.status_code == 200
            assert retried.json()["submission"]["status"] == "published"

        with factory() as session:
            attempts = session.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.object_id == "failed-submission")
                .order_by(ProcessingJob.attempt_count)
            ).all()
            assert [job.attempt_count for job in attempts] == [1, 2]
            assert attempts[-1].status == "completed"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
