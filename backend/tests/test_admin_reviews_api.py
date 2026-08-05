"""管理员审核、发布、审计和用户越权回归。"""

from pathlib import Path
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.admin_reviews import get_review_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import (
    AuditEvent,
    DocumentVersion,
    KnowledgeDocument,
    KnowledgeSubmission,
    ProcessingJob,
)
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.tokens import get_token_service
from app.modules.jobs.service import SqlAlchemyJobService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.deduplication import DuplicatePolicy
from app.modules.knowledge.repository import SubmissionReviewRepository
from app.modules.knowledge.review_service import KnowledgeReviewService
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_document_service import FakeVectorStore


def make_png_bytes() -> bytes:
    image = Image.new("RGB", (2, 2), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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


def add_fingerprinted_published_document(factory, settings, vectors, suffix, text):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    document_id = f"published-{suffix}"
    stored_name = f"{document_id}.txt"
    (settings.upload_dir / stored_name).write_text(text, encoding="utf-8")
    chunk_id = f"{document_id}:0"
    fingerprint = DuplicatePolicy.fingerprint_text(text)
    with factory() as session:
        session.add(
            KnowledgeDocument(
                id=document_id,
                original_name=f"已发布{suffix}.txt",
                stored_name=stored_name,
                content_hash=("9" + suffix[0]) * 32,
                size_bytes=len(text.encode("utf-8")),
                chunk_count=1,
                chunk_ids=[chunk_id],
                uploader_id=None,
                is_system=True,
                status="published",
            )
        )
        session.add(
            DocumentVersion(
                id=f"published-version-{suffix}",
                document_id=document_id,
                version=1,
                source="system",
                tags=[],
                parser_version="knowledge_parser_v1",
                corpus_version="live_v1",
                normalized_text_hash=fingerprint.normalized_text_hash,
                normalized_text_hash_version=fingerprint.normalized_text_hash_version,
                near_duplicate_fingerprint=fingerprint.near_duplicate_fingerprint,
                near_duplicate_fingerprint_version=fingerprint.near_duplicate_fingerprint_version,
            )
        )
        session.commit()
    vectors.entries[chunk_id] = {
        "document": text,
        "metadata": {"document_id": document_id},
        "embedding": [0.1],
    }
    return document_id


def add_markdown_submission(factory, settings, submitter_id, suffix):
    settings.submission_dir.mkdir(parents=True, exist_ok=True)
    submission_id = f"review-md-{suffix}"
    stored_name = f"{submission_id}.md"
    (settings.submission_dir / stored_name).write_text(
        "# 审核标题\n\n| 项目 | 说明 |\n| --- | --- |\n| 血压 | 每日记录 |\n",
        encoding="utf-8",
    )
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id=submission_id,
                submitter_id=submitter_id,
                original_name=f"审核资料{suffix}.md",
                stored_name=stored_name,
                content_hash=(suffix[0] * 64),
                size_bytes=80,
                status="pending_review",
                preview_text=f"预览{suffix}",
                preview_pages=1,
                parse_warnings=[],
            )
        )
        session.commit()
    return submission_id


def add_web_snapshot_submission(factory, settings, submitter_id, suffix):
    settings.submission_dir.mkdir(parents=True, exist_ok=True)
    submission_id = f"review-web-{suffix}"
    stored_name = f"{submission_id}.html"
    content = (
        "<html><body><h1>网页标题</h1><p>网页正文</p>"
        "<table><tr><td>项目</td><td>说明</td></tr></table></body></html>"
    )
    (settings.submission_dir / stored_name).write_text(content, encoding="utf-8")
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id=submission_id,
                submitter_id=submitter_id,
                original_name="网页快照-example.com.html",
                stored_name=stored_name,
                content_hash=(suffix[0] * 64),
                size_bytes=len(content.encode()),
                status="pending_review",
                preview_text="网页标题\n\n网页正文",
                preview_pages=1,
                parse_warnings=[],
                snapshot_original_url="https://example.com/article",
                snapshot_final_url="https://example.com/article",
                snapshot_response_mime="text/html",
                snapshot_content_sha256=(suffix[0] * 64),
            )
        )
        session.commit()
    return submission_id


def add_image_submission(factory, settings, submitter_id, suffix):
    settings.submission_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = settings.document_asset_dir / "submissions" / f"review-image-{suffix}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    submission_id = f"review-image-{suffix}"
    stored_name = f"{submission_id}.png"
    content = make_png_bytes()
    (settings.submission_dir / stored_name).write_bytes(content)
    (asset_dir / "asset.png").write_bytes(content)
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id=submission_id,
                submitter_id=submitter_id,
                original_name=f"report-{suffix}.png",
                stored_name=stored_name,
                content_hash=(suffix[0] * 64),
                size_bytes=len(content),
                status="pending_review",
                preview_text="",
                preview_pages=1,
                parse_warnings=[
                    "Image document is waiting for OCR/Vision enrichment before publication."
                ],
                parse_quality={
                    "status": "warning",
                    "counts": {"scanned_or_image": 1, "asset": 1},
                    "enrichment": {"status": "waiting_enrichment", "asset_count": 1},
                },
            )
        )
        session.commit()
    return submission_id


def add_damaged_docx_submission(factory, settings, submitter_id, suffix):
    settings.submission_dir.mkdir(parents=True, exist_ok=True)
    submission_id = f"review-docx-{suffix}"
    stored_name = f"{submission_id}.docx"
    with ZipFile(settings.submission_dir / stored_name, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id=submission_id,
                submitter_id=submitter_id,
                original_name=f"损坏{suffix}.docx",
                stored_name=stored_name,
                content_hash=(suffix[0] * 64),
                size_bytes=40,
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
        document_asset_dir=tmp_path / "assets",
        chunk_size=30,
        chunk_overlap=5,
    )
    rejected_id = add_submission(factory, settings, submitter.id, "a")
    approved_id = add_submission(factory, settings, submitter.id, "b")
    approved_asset_dir = settings.document_asset_dir / "submissions" / approved_id
    approved_asset_dir.mkdir(parents=True, exist_ok=True)
    (approved_asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")
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
            assert not (settings.document_asset_dir / "submissions" / approved_id).exists()
            assert (
                settings.document_asset_dir / "documents" / published.document_id
            ).is_dir()
            chunk_text = " ".join(
                item["document"] for item in vectors.entries.values()
            )
            assert "审核资料b" in chunk_text
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


def test_admin_sees_duplicate_candidates_and_can_publish_submission_as_new_version(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-duplicates.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "review-duplicate-submitter")
    admin = create_test_user(factory, "review-duplicate-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=80,
        chunk_overlap=5,
    )
    vectors = FakeVectorStore()
    old_document_id = add_fingerprinted_published_document(
        factory,
        settings,
        vectors,
        "base",
        "心力衰竭 随访 用药 复查 血压",
    )
    submission_id = add_submission(factory, settings, submitter.id, "v")
    with factory() as session:
        submission = session.get(KnowledgeSubmission, submission_id)
        submission.preview_text = "心力衰竭  随访\n用药 复查 血压"
        DuplicatePolicy.assign_to_submission(submission)
        session.commit()

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
            listed = client.get(
                "/api/v1/admin/reviews",
                headers=auth_headers(admin.id),
            )
            assert listed.status_code == 200
            candidates = listed.json()["items"][0]["duplicate_candidates"]
            assert any(
                item["duplicate_type"] == "normalized"
                and item["candidate_document_id"] == old_document_id
                for item in candidates
            )

            published = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve-as-version",
                json={
                    "supersedes_document_id": old_document_id,
                    "change_reason": "同主题指南更新",
                },
                headers=auth_headers(admin.id),
            )
            assert published.status_code == 200
            assert published.json()["submission"]["duplicate_decision"] == "version"

        with factory() as session:
            old = session.get(KnowledgeDocument, old_document_id)
            submission = session.get(KnowledgeSubmission, submission_id)
            new_version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == submission.document_id
                )
            )
            assert old.status == "archived"
            assert new_version.version == 2
            assert new_version.supersedes_document_id == old_document_id
            assert new_version.replaces_document_id == old_document_id
            assert new_version.change_reason == "同主题指南更新"
            assert new_version.normalized_text_hash_version == "normalized_text_sha256_v1"
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert "knowledge_submission.published" in actions
        assert not any(
            value["metadata"]["document_id"] == old_document_id
            for value in vectors.entries.values()
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_approve_as_version_failure_restores_old_vectors_and_cleans_new_document(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-version-failure.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "review-version-failure-submitter")
    admin = create_test_user(factory, "review-version-failure-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=80,
        chunk_overlap=5,
    )
    vectors = FakeVectorStore()
    old_document_id = add_fingerprinted_published_document(
        factory,
        settings,
        vectors,
        "rollback",
        "心力衰竭 随访 用药 复查 血压",
    )
    old_entries = dict(vectors.entries)
    submission_id = add_submission(factory, settings, submitter.id, "rollback")
    with factory() as session:
        submission = session.get(KnowledgeSubmission, submission_id)
        submission.preview_text = "心力衰竭 随访 用药 复查 血压 更新"
        DuplicatePolicy.assign_to_submission(submission)
        session.commit()

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
                f"/api/v1/admin/reviews/{submission_id}/approve-as-version",
                json={
                    "supersedes_document_id": old_document_id,
                    "change_reason": "失败回滚测试",
                },
                headers=auth_headers(admin.id),
            )
            assert response.status_code == 500
            assert response.json()["error"]["code"] == "DOCUMENT_STORE_ERROR"

        with factory() as session:
            old = session.get(KnowledgeDocument, old_document_id)
            submission = session.get(KnowledgeSubmission, submission_id)
            documents = session.scalars(select(KnowledgeDocument)).all()
            job = session.scalar(select(ProcessingJob))
            assert old.status == "published"
            assert submission.status == "failed"
            assert submission.document_id is None
            assert job.status == "failed"
            assert [document.id for document in documents] == [old_document_id]
            assert session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.supersedes_document_id == old_document_id
                )
            ) is None
        assert vectors.entries == old_entries
        assert vectors.restore_calls == 1
        assert len(list(settings.upload_dir.glob("*.txt"))) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_document_version_supersedes_version_unique_constraint_blocks_double_branch(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'version-constraint.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        for document_id in ("old", "new-a", "new-b"):
            session.add(
                KnowledgeDocument(
                    id=document_id,
                    original_name=f"{document_id}.txt",
                    stored_name=f"{document_id}.txt",
                    content_hash=(document_id[-1] * 64),
                    size_bytes=10,
                    chunk_count=1,
                    chunk_ids=[f"{document_id}:0"],
                    uploader_id=None,
                    is_system=True,
                    status="published",
                )
            )
        session.add_all(
            [
                DocumentVersion(
                    id="version-old",
                    document_id="old",
                    version=1,
                    source="system",
                    tags=[],
                ),
                DocumentVersion(
                    id="version-new-a",
                    document_id="new-a",
                    version=2,
                    supersedes_document_id="old",
                    source="system",
                    tags=[],
                ),
                DocumentVersion(
                    id="version-new-b",
                    document_id="new-b",
                    version=2,
                    supersedes_document_id="old",
                    source="system",
                    tags=[],
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()



def test_image_review_status_is_visible_and_reject_cleans_assets(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'image-review.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "image-review-submitter")
    admin = create_test_user(factory, "image-review-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        document_asset_dir=tmp_path / "assets",
    )
    submission_id = add_image_submission(factory, settings, submitter.id, "r")
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
            listed = client.get(
                "/api/v1/admin/reviews",
                headers=auth_headers(admin.id),
            )
            assert listed.status_code == 200
            item = listed.json()["items"][0]
            assert item["parse_quality"]["enrichment"]["status"] == "waiting_enrichment"

            rejected = client.post(
                f"/api/v1/admin/reviews/{submission_id}/reject",
                json={"reason": "needs manual OCR"},
                headers=auth_headers(admin.id),
            )
            assert rejected.status_code == 200
            assert rejected.json()["submission"]["status"] == "rejected"

        assert not (settings.document_asset_dir / "submissions" / submission_id).exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_reject_post_commit_asset_cleanup_failure_records_pending(
    tmp_path, monkeypatch
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'image-review-pending.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "image-review-pending-submitter")
    admin = create_test_user(factory, "image-review-pending-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        document_asset_dir=tmp_path / "assets",
    )
    submission_id = add_image_submission(factory, settings, submitter.id, "pending")
    original_rmtree = __import__("shutil").rmtree

    def fail_trash_rmtree(path):
        if ".trash" in Path(path).parts:
            raise OSError("simulated reject cleanup failure")
        return original_rmtree(path)

    monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_trash_rmtree)
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
            rejected = client.post(
                f"/api/v1/admin/reviews/{submission_id}/reject",
                json={"reason": "needs manual OCR"},
                headers=auth_headers(admin.id),
            )
            assert rejected.status_code == 200
            assert rejected.json()["submission"]["status"] == "rejected"

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            assert submission.status == "rejected"
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert "knowledge_submission.cleanup_pending" in actions
        assert list((settings.document_asset_dir / ".cleanup_pending").glob("*.json"))
        assert not (settings.document_asset_dir / "submissions" / submission_id).exists()
        assert list((settings.document_asset_dir / ".trash" / "submissions").glob("*"))
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_reject_marker_write_failure_still_returns_success(
    tmp_path, monkeypatch
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'image-review-marker.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "image-review-marker-submitter")
    admin = create_test_user(factory, "image-review-marker-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        document_asset_dir=tmp_path / "assets",
    )
    submission_id = add_image_submission(factory, settings, submitter.id, "marker")
    original_rmtree = __import__("shutil").rmtree

    def fail_trash_rmtree(path):
        if ".trash" in Path(path).parts:
            raise OSError("simulated reject cleanup failure")
        return original_rmtree(path)

    def fail_mark_cleanup_pending(self, staged, *, reason):
        del self, staged, reason
        raise OSError("simulated marker write failure")

    monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_trash_rmtree)
    monkeypatch.setattr(
        "app.modules.knowledge.asset_storage.ControlledDocumentAssetStore.mark_cleanup_pending",
        fail_mark_cleanup_pending,
    )
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
            rejected = client.post(
                f"/api/v1/admin/reviews/{submission_id}/reject",
                json={"reason": "needs manual OCR"},
                headers=auth_headers(admin.id),
            )
            assert rejected.status_code == 200
            assert rejected.json()["submission"]["status"] == "rejected"

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            assert submission.status == "rejected"
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert "knowledge_submission.cleanup_pending" in actions
        assert not list((settings.document_asset_dir / ".cleanup_pending").glob("*.json"))
        assert not (settings.document_asset_dir / "submissions" / submission_id).exists()
        assert list((settings.document_asset_dir / ".trash" / "submissions").glob("*"))
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_image_review_cannot_publish_empty_text_before_enrichment(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'image-review-fail.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "image-review-fail-submitter")
    admin = create_test_user(factory, "image-review-fail-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        document_asset_dir=tmp_path / "assets",
    )
    submission_id = add_image_submission(factory, settings, submitter.id, "p")
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
            approved = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code >= 400

        with factory() as session:
            record = session.get(KnowledgeSubmission, submission_id)
            assert record.status == "failed"
            assert session.scalar(select(KnowledgeDocument)) is None
        assert not vectors.added_ids
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


def test_admin_can_publish_markdown_submission_with_structured_chunks(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-markdown.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "review-markdown-submitter")
    admin = create_test_user(factory, "review-markdown-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=80,
        chunk_overlap=5,
    )
    submission_id = add_markdown_submission(factory, settings, submitter.id, "f")
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
            approved = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code == 200
            assert approved.json()["submission"]["status"] == "published"

        with factory() as session:
            published = session.get(KnowledgeSubmission, submission_id)
            document = session.get(KnowledgeDocument, published.document_id)
            assert document.original_name.endswith(".md")
        indexed_text = "\n".join(item["document"] for item in vectors.entries.values())
        assert "# 审核标题" in indexed_text
        assert "血压 | 每日记录" in indexed_text
        assert all(
            item["metadata"]["document_type"] == "md"
            for item in vectors.entries.values()
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_can_publish_web_snapshot_submission_with_html_parser(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-web.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "review-web-submitter")
    admin = create_test_user(factory, "review-web-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=80,
        chunk_overlap=5,
    )
    submission_id = add_web_snapshot_submission(factory, settings, submitter.id, "w")
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
            approved = client.post(
                f"/api/v1/admin/reviews/{submission_id}/approve",
                headers=auth_headers(admin.id),
            )
            assert approved.status_code == 200
            assert approved.json()["submission"]["status"] == "published"

        with factory() as session:
            submission = session.get(KnowledgeSubmission, submission_id)
            document = session.get(KnowledgeDocument, submission.document_id)
            assert document is not None
            assert document.original_name == "网页快照-example.com.html"
            chunk_text = " ".join(item["document"] for item in vectors.entries.values())
            assert "# 网页标题" in chunk_text
            assert "网页正文" in chunk_text
            assert any(
                item["metadata"]["document_type"] == "html"
                for item in vectors.entries.values()
            )
        assert not (settings.submission_dir / f"{submission_id}.html").exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_damaged_docx_publish_failure_keeps_submission_file_and_no_vectors(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'review-docx-failure.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    submitter = create_test_user(factory, "review-docx-submitter")
    admin = create_test_user(factory, "review-docx-admin", role="admin")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        upload_dir=tmp_path / "published",
        chunk_size=80,
        chunk_overlap=5,
    )
    submission_id = add_damaged_docx_submission(factory, settings, submitter.id, "g")
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
        assert vectors.entries == {}
        assert (settings.submission_dir / f"{submission_id}.docx").exists()
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
