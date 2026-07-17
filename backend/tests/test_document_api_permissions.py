"""文档 API 权限测试：公共可见、上传者删除、系统文档保护。"""

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import KnowledgeDocument
from app.modules.auth.tokens import get_token_service
from app.services.document_service import DocumentService, get_document_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_document_service import FakeVectorStore


def test_document_api_requires_login_and_enforces_public_permissions(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'document-api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "document-api-owner")
    other = create_test_user(factory, "document-api-other")
    vector_store = FakeVectorStore()
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "legacy-documents.json",
        chunk_size=30,
        chunk_overlap=5,
    )

    def override_session():
        with factory() as session:
            yield session

    def override_document_service(
        session: Session = Depends(get_db_session),
    ) -> DocumentService:
        return DocumentService(session, settings=settings, vector_store=vector_store)

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_document_service] = override_document_service
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/documents").status_code == 401

            upload = client.post(
                "/api/v1/documents",
                files={"file": ("公共资料.txt", "公共医学资料".encode(), "text/plain")},
                headers=auth_headers(owner.id),
            )
            assert upload.status_code == 201
            document_id = upload.json()["document_id"]
            assert upload.json()["can_delete"] is True

            other_list = client.get(
                "/api/v1/documents", headers=auth_headers(other.id)
            )
            assert other_list.status_code == 200
            assert other_list.json()["total"] == 1
            assert other_list.json()["documents"][0]["can_delete"] is False

            forbidden = client.delete(
                f"/api/v1/documents/{document_id}", headers=auth_headers(other.id)
            )
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "DOCUMENT_DELETE_FORBIDDEN"

            deleted = client.delete(
                f"/api/v1/documents/{document_id}", headers=auth_headers(owner.id)
            )
            assert deleted.status_code == 200
            assert client.get(
                "/api/v1/documents", headers=auth_headers(other.id)
            ).json()["total"] == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_system_document_is_public_but_not_deletable(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'system-document-api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "system-reader")
    vector_store = FakeVectorStore()
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "legacy-documents.json",
    )
    settings.upload_dir.mkdir(parents=True)
    (settings.upload_dir / "system.txt").write_text("系统公共资料", encoding="utf-8")
    with factory() as session:
        session.add(
            KnowledgeDocument(
                id="system-public-document",
                original_name="系统公共资料.txt",
                stored_name="system.txt",
                content_hash="b" * 64,
                size_bytes=18,
                chunk_count=1,
                chunk_ids=["system-public-document:0"],
                uploader_id=None,
                is_system=True,
                status="ready",
            )
        )
        session.commit()
    vector_store.entries["system-public-document:0"] = {
        "document": "系统公共资料",
        "metadata": {"document_id": "system-public-document"},
        "embedding": [0.1, 0.2],
    }

    def override_session():
        with factory() as session:
            yield session

    def override_document_service(
        session: Session = Depends(get_db_session),
    ) -> DocumentService:
        return DocumentService(session, settings=settings, vector_store=vector_store)

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_document_service] = override_document_service
    try:
        with TestClient(app) as client:
            headers = auth_headers(user.id)
            listed = client.get("/api/v1/documents", headers=headers)
            assert listed.json()["documents"][0]["is_system"] is True
            assert listed.json()["documents"][0]["can_delete"] is False

            forbidden = client.delete(
                "/api/v1/documents/system-public-document", headers=headers
            )
            assert forbidden.status_code == 403
            assert (settings.upload_dir / "system.txt").exists()
            assert "system-public-document:0" in vector_store.entries
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
