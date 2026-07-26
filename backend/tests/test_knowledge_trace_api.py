"""已发布文档引用追溯、原文预览和状态隔离回归。"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import DocumentVersion, KnowledgeDocument
from app.modules.auth.tokens import get_token_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def test_trace_and_preview_only_expose_published_documents(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'trace.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "trace-user")
    upload_dir = tmp_path / "published"
    upload_dir.mkdir()
    (upload_dir / "trace-document.txt").write_text("可追溯正文", encoding="utf-8")
    with factory() as session:
        session.add(
            KnowledgeDocument(
                id="trace-document",
                original_name="追溯资料.txt",
                stored_name="trace-document.txt",
                content_hash="a" * 64,
                size_bytes=18,
                chunk_count=1,
                chunk_ids=["trace-document:0"],
                uploader_id=None,
                is_system=True,
                status="published",
            )
        )
        session.add(
            DocumentVersion(
                id="trace-version",
                document_id="trace-document",
                version=2,
                source="国家指南",
                tags=["安全"],
                category="诊疗规范",
                department="外科",
                review_due_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, upload_dir=upload_dir
    )
    try:
        with TestClient(app) as client:
            assert client.get(
                "/api/v1/knowledge/documents/trace-document/trace"
            ).status_code == 401
            trace = client.get(
                "/api/v1/knowledge/documents/trace-document/trace",
                headers=auth_headers(user.id),
            )
            assert trace.status_code == 200
            assert trace.json()["version"] == 2
            assert trace.json()["category"] == "诊疗规范"
            assert trace.json()["department"] == "外科"
            preview = client.get(
                "/api/v1/knowledge/documents/trace-document/preview",
                headers=auth_headers(user.id),
            )
            assert preview.status_code == 200
            assert preview.content.decode("utf-8") == "可追溯正文"

            with factory() as session:
                session.get(KnowledgeDocument, "trace-document").status = "archived"
                session.commit()
            assert client.get(
                "/api/v1/knowledge/documents/trace-document/trace",
                headers=auth_headers(user.id),
            ).status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
