"""管理员系统文档 API 权限和真实路由数据流测试。"""

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.tokens import get_token_service
from app.services.admin_document_service import (
    AdminDocumentService,
    get_admin_document_service,
)
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.test_document_service import FakeVectorStore


def test_admin_document_routes_reject_spoofing_and_complete_crud(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'admin-api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    normal_user = create_test_user(factory, "normal-admin-api")
    admin = create_test_user(factory, "admin-api", role="admin")
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "documents.json",
        chunk_size=30,
        chunk_overlap=5,
    )
    vector_store = FakeVectorStore()

    def override_session():
        with factory() as session:
            yield session

    def override_admin_service(
        session: Session = Depends(get_db_session),
    ) -> AdminDocumentService:
        return AdminDocumentService(session, settings=settings, vector_store=vector_store)

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_admin_document_service] = override_admin_service
    try:
        with TestClient(app) as client:
            forbidden = client.post(
                "/api/v1/admin/documents",
                files={"file": ("伪造.txt", "不能上传".encode(), "text/plain")},
                headers={**auth_headers(normal_user.id), "X-User-Role": "admin"},
            )
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "ADMIN_REQUIRED"

            created = client.post(
                "/api/v1/admin/documents",
                files={"file": ("系统.txt", "系统内容".encode(), "text/plain")},
                headers=auth_headers(admin.id),
            )
            assert created.status_code == 201
            old_id = created.json()["document_id"]
            assert created.json()["is_system"] is True

            replaced = client.put(
                f"/api/v1/admin/documents/{old_id}/replace",
                files={"file": ("系统新版.txt", "新版系统内容".encode(), "text/plain")},
                headers=auth_headers(admin.id),
            )
            assert replaced.status_code == 200
            new_id = replaced.json()["document_id"]
            assert new_id != old_id

            deleted = client.delete(
                f"/api/v1/admin/documents/{new_id}", headers=auth_headers(admin.id)
            )
            assert deleted.status_code == 200
            assert not vector_store.entries
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
