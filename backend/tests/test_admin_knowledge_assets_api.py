"""知识资产元数据、下线、重发和替换回归。"""

import hashlib

from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.api.admin_knowledge_assets import get_asset_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import AuditEvent, DocumentVersion, KnowledgeDocument
from app.modules.knowledge.deduplication import DuplicatePolicy
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.tokens import get_token_service
from app.modules.knowledge.asset_service import KnowledgeAssetService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.jobs.models import ProcessingJob
from app.modules.jobs.service import SqlAlchemyJobService
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_document_service import FakeVectorStore


def add_asset(factory, settings, vectors, suffix):
    document_id = f"asset-{suffix}"
    stored_name = f"{document_id}.txt"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / stored_name).write_text(
        f"知识资产{suffix}", encoding="utf-8"
    )
    chunk_id = f"{document_id}:0"
    fingerprint = DuplicatePolicy.fingerprint_text(f"知识资产{suffix}")
    with factory() as session:
        session.add(
            KnowledgeDocument(
                id=document_id,
                original_name=f"知识资产{suffix}.txt",
                stored_name=stored_name,
                content_hash=hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
                size_bytes=20,
                chunk_count=1,
                chunk_ids=[chunk_id],
                uploader_id=None,
                is_system=True,
                status="published",
            )
        )
        session.add(
            DocumentVersion(
                id=f"version-{suffix}",
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
        "document": f"知识资产{suffix}",
        "metadata": {"document_id": document_id},
        "embedding": [0.1],
    }
    return document_id


def test_asset_metadata_archive_republish_and_replace(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'assets.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    normal = create_test_user(factory, "asset-normal")
    admin = create_test_user(factory, "asset-admin", role="admin")
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    vectors = FakeVectorStore()
    first_id = add_asset(factory, settings, vectors, "d")
    second_id = add_asset(factory, settings, vectors, "e")

    def override_session():
        with factory() as session:
            yield session

    def override_asset_service():
        with factory() as session:
            yield KnowledgeAssetService(
                session,
                DocumentLifecycleService(session, settings, vectors),
                SqlAlchemyAuditRecorder(session),
                SqlAlchemyJobService(session),
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_asset_service] = override_asset_service
    try:
        with TestClient(app) as client:
            assert client.get(
                "/api/v1/admin/knowledge-assets",
                headers=auth_headers(normal.id),
            ).status_code == 403

            updated = client.patch(
                f"/api/v1/admin/knowledge-assets/{first_id}",
                json={"source": "临床指南", "tags": ["心血管", "指南", "指南"]},
                headers=auth_headers(admin.id),
            )
            assert updated.status_code == 200
            assert updated.json()["tags"] == ["心血管", "指南"]

            governance_metadata = client.patch(
                f"/api/v1/admin/knowledge-assets/{first_id}",
                json={
                    "source": "临床指南",
                    "tags": ["心血管", "指南"],
                    "category": "诊疗规范",
                    "department": "心内科",
                    "expires_at": (
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                    "review_due_at": (
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                },
                headers=auth_headers(admin.id),
            )
            assert governance_metadata.status_code == 200
            assert governance_metadata.json()["department"] == "心内科"
            with factory() as session:
                second_version = session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == second_id
                    )
                )
                second_version.review_due_at = datetime.now(timezone.utc) - timedelta(
                    days=1
                )
                second_version.review_status = "current"
                session.commit()
            assert client.post(
                "/api/v1/admin/knowledge-assets/governance/scan",
                headers=auth_headers(normal.id),
            ).status_code == 403
            scan = client.post(
                "/api/v1/admin/knowledge-assets/governance/scan",
                headers=auth_headers(admin.id),
            )
            assert scan.status_code == 200
            assert scan.json()["count"] == 1
            assert scan.json()["duplicate_scan"]["updated"] == 0
            with factory() as session:
                first_version = session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == first_id
                    )
                )
                assert first_version.review_status != "in_review"
            in_review = client.get(
                "/api/v1/admin/knowledge-assets?review_status=in_review",
                headers=auth_headers(admin.id),
            )
            assert in_review.json()["total"] == 1
            expired = client.get(
                "/api/v1/admin/knowledge-assets?expired=true",
                headers=auth_headers(admin.id),
            )
            assert expired.json()["total"] == 1
            assert expired.json()["items"][0]["is_system"] is True
            assert client.post(
                "/api/v1/admin/knowledge-assets/governance/scan",
                headers=auth_headers(admin.id),
            ).json()["count"] == 0
            reviewed = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/review",
                json={
                    "next_review_due_at": (
                        datetime.now(timezone.utc) + timedelta(days=180)
                    ).isoformat(),
                    "note": "已核对现行指南",
                },
                headers=auth_headers(admin.id),
            )
            assert reviewed.status_code == 200
            assert reviewed.json()["review_status"] == "current"
            due = client.get(
                "/api/v1/admin/knowledge-assets?review_status=due",
                headers=auth_headers(admin.id),
            )
            assert due.json()["total"] == 0
            filtered = client.get(
                "/api/v1/admin/knowledge-assets?tag=心血管",
                headers=auth_headers(admin.id),
            )
            assert filtered.json()["total"] == 1

            expired_mark = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/expire",
                json={"reason": "资料来源已失效"},
                headers=auth_headers(admin.id),
            )
            assert expired_mark.status_code == 200
            assert expired_mark.json()["governance_status"] == "expired"
            stale_restore = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/restore",
                json={
                    "next_review_due_at": (
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                    "note": "过期复核时间不允许",
                },
                headers=auth_headers(admin.id),
            )
            assert stale_restore.status_code == 409
            restored = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/restore",
                json={
                    "next_review_due_at": (
                        datetime.now(timezone.utc) + timedelta(days=90)
                    ).isoformat(),
                    "note": "已确认仍可使用",
                },
                headers=auth_headers(admin.id),
            )
            assert restored.status_code == 200
            assert restored.json()["governance_status"] == "current"
            deferred = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/review/defer",
                json={
                    "next_review_due_at": (
                        datetime.now(timezone.utc) + timedelta(days=120)
                    ).isoformat(),
                    "note": "延后复核",
                },
                headers=auth_headers(admin.id),
            )
            assert deferred.status_code == 200

            archived = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/archive",
                headers=auth_headers(admin.id),
            )
            assert archived.json()["status"] == "archived"
            assert not any(
                value["metadata"]["document_id"] == first_id
                for value in vectors.entries.values()
            )

            republished = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/republish",
                headers=auth_headers(admin.id),
            )
            assert republished.status_code == 200
            assert republished.json()["status"] == "published"

            replaced = client.post(
                f"/api/v1/admin/knowledge-assets/{first_id}/replace",
                json={"replacement_document_id": second_id},
                headers=auth_headers(admin.id),
            )
            assert replaced.status_code == 200
            assert replaced.json()["version"] == 2
            assert replaced.json()["replaces_document_id"] == first_id

        with factory() as session:
            assert session.get(KnowledgeDocument, first_id).status == "archived"
            actions = set(session.scalars(select(AuditEvent.action)).all())
            assert {
                "knowledge_asset.metadata_updated",
                "knowledge_asset.archived",
                "knowledge_asset.republished",
                "knowledge_asset.replaced",
                "knowledge_asset.reviewed",
                "knowledge_asset.expired_marked",
                "knowledge_asset.restored_current",
                "knowledge_asset.review_deferred",
            } <= actions
            review_job = session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.object_id == second_id,
                    ProcessingJob.job_type == "knowledge_review",
                )
            )
            assert review_job is not None
            assert review_job.status == "running"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_asset_duplicate_candidates_and_fingerprint_scan_are_visible(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'assets-dedup.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    admin = create_test_user(factory, "asset-dedup-admin", role="admin")
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    vectors = FakeVectorStore()
    first_id = add_asset(factory, settings, vectors, "x")
    second_id = add_asset(factory, settings, vectors, "y")
    with factory() as session:
        first_version = session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == first_id)
        )
        second_version = session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == second_id)
        )
        second_version.normalized_text_hash = first_version.normalized_text_hash
        second_version.normalized_text_hash_version = first_version.normalized_text_hash_version
        second_version.near_duplicate_fingerprint = first_version.near_duplicate_fingerprint
        second_version.near_duplicate_fingerprint_version = (
            first_version.near_duplicate_fingerprint_version
        )
        first_version.normalized_text_hash = None
        first_version.normalized_text_hash_version = None
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    def override_asset_service():
        with factory() as session:
            yield KnowledgeAssetService(
                session,
                DocumentLifecycleService(session, settings, vectors),
                SqlAlchemyAuditRecorder(session),
                SqlAlchemyJobService(session),
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_asset_service] = override_asset_service
    try:
        with TestClient(app) as client:
            scan = client.post(
                "/api/v1/admin/knowledge-assets/governance/scan",
                headers=auth_headers(admin.id),
            )
            assert scan.status_code == 200
            assert scan.json()["duplicate_scan"]["updated"] == 1
            assert scan.json()["duplicate_scan"]["remaining"] is False

            listed = client.get(
                "/api/v1/admin/knowledge-assets",
                headers=auth_headers(admin.id),
            )
            assert listed.status_code == 200
            candidates = [
                candidate
                for item in listed.json()["items"]
                for candidate in item["duplicate_candidates"]
            ]
            assert any(
                candidate["duplicate_type"] == "normalized"
                for candidate in candidates
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_asset_list_prefetches_duplicate_candidates_without_per_item_queries(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'assets-batch.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    admin = create_test_user(factory, "asset-batch-admin", role="admin")
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    vectors = FakeVectorStore()
    ids = [add_asset(factory, settings, vectors, f"b{index}") for index in range(6)]
    with factory() as session:
        first_version = session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == ids[0])
        )
        for document_id in ids[1:]:
            version = session.scalar(
                select(DocumentVersion).where(DocumentVersion.document_id == document_id)
            )
            version.normalized_text_hash = first_version.normalized_text_hash
            version.normalized_text_hash_version = first_version.normalized_text_hash_version
        session.commit()

    query_count = 0

    def count_queries(*args):
        nonlocal query_count
        del args
        query_count += 1

    def override_session():
        with factory() as session:
            yield session

    def override_asset_service():
        with factory() as session:
            yield KnowledgeAssetService(
                session,
                DocumentLifecycleService(session, settings, vectors),
                SqlAlchemyAuditRecorder(session),
                SqlAlchemyJobService(session),
            )

    event.listen(engine, "before_cursor_execute", count_queries)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_asset_service] = override_asset_service
    try:
        with TestClient(app) as client:
            listed = client.get(
                "/api/v1/admin/knowledge-assets?limit=6",
                headers=auth_headers(admin.id),
            )
            assert listed.status_code == 200
            assert listed.json()["total"] == 6
            assert any(
                item["duplicate_candidates"] for item in listed.json()["items"]
            )
        assert query_count <= 12
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
        app.dependency_overrides.clear()
        engine.dispose()


def test_duplicate_fingerprint_scan_is_batched_and_reports_remaining(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'assets-scan-batch.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "published",
        chunk_size=30,
        chunk_overlap=5,
    )
    vectors = FakeVectorStore()
    for index in range(105):
        document_id = add_asset(factory, settings, vectors, f"s{index}")
        with factory() as session:
            version = session.scalar(
                select(DocumentVersion).where(DocumentVersion.document_id == document_id)
            )
            version.normalized_text_hash = None
            version.normalized_text_hash_version = None
            session.commit()

    with factory() as session:
        service = KnowledgeAssetService(
            session,
            DocumentLifecycleService(session, settings, vectors),
            SqlAlchemyAuditRecorder(session),
            SqlAlchemyJobService(session),
        )

        result = service.scan_duplicate_fingerprints()

        assert result["scanned"] == 100
        assert result["updated"] == 100
        assert result["remaining"] is True
    engine.dispose()
