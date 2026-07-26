"""知识资产元数据、下线、重发和替换回归。"""

from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.admin_knowledge_assets import get_asset_service
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import AuditEvent, DocumentVersion, KnowledgeDocument
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
    with factory() as session:
        session.add(
            KnowledgeDocument(
                id=document_id,
                original_name=f"知识资产{suffix}.txt",
                stored_name=stored_name,
                content_hash=suffix[0] * 64,
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
                    "review_due_at": (
                        datetime.now(timezone.utc) - timedelta(days=1)
                    ).isoformat(),
                },
                headers=auth_headers(admin.id),
            )
            assert governance_metadata.status_code == 200
            assert governance_metadata.json()["department"] == "心内科"
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
            filtered = client.get(
                "/api/v1/admin/knowledge-assets?tag=心血管",
                headers=auth_headers(admin.id),
            )
            assert filtered.json()["total"] == 1

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
            } <= actions
            review_job = session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.object_id == first_id,
                    ProcessingJob.job_type == "knowledge_review",
                )
            )
            assert review_job is not None
            assert review_job.status == "completed"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
