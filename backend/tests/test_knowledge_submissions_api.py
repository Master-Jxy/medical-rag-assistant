"""普通资料只进入隔离提交，不写公共文档或向量库。"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.tokens import get_token_service
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeSubmission
from app.modules.knowledge.parser import LocalDocumentParser, ParsedPreview
from app.modules.knowledge.submission_service import KnowledgeSubmissionService
from app.api.knowledge_submissions import get_submission_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


class FakeParser:
    def parse(self, _path, _suffix):
        return ParsedPreview("解析预览", 1)


def test_submit_parse_list_and_withdraw_are_isolated_without_publication(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'submissions.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "submission-owner")
    other = create_test_user(factory, "submission-other")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")

    def override_session():
        with factory() as session:
            yield session

    def override_service():
        with factory() as session:
            yield KnowledgeSubmissionService(session, settings, FakeParser())

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_submission_service] = override_service
    try:
        with TestClient(app) as client:
            assert client.post(
                "/api/v1/documents",
                files={"file": ("旁路.txt", b"blocked", "text/plain")},
                headers=auth_headers(owner.id),
            ).status_code == 405

            created = client.post(
                "/api/v1/knowledge/submissions",
                files={"file": ("待审核.txt", "医学资料".encode(), "text/plain")},
                headers=auth_headers(owner.id),
            )
            assert created.status_code == 202
            assert created.json()["status"] == "pending_review"
            submission_id = created.json()["submission_id"]

            assert client.get(
                "/api/v1/knowledge/submissions",
                headers=auth_headers(other.id),
            ).json()["total"] == 0
            assert client.post(
                f"/api/v1/knowledge/submissions/{submission_id}/withdraw",
                headers=auth_headers(other.id),
            ).status_code == 404
            withdrawn = client.post(
                f"/api/v1/knowledge/submissions/{submission_id}/withdraw",
                headers=auth_headers(owner.id),
            )
            assert withdrawn.status_code == 200
            assert withdrawn.json()["status"] == "withdrawn"

        with factory() as session:
            saved = session.get(KnowledgeSubmission, submission_id)
            assert saved is not None and saved.preview_text == "解析预览"
            assert session.scalar(
                select(func.count()).select_from(KnowledgeDocument)
            ) == 0
        assert not list(settings.submission_dir.glob("*"))
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_submission_entry_uses_structured_parser_compatibility(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'structured-submissions.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "structured-submission-owner")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")

    def override_session():
        with factory() as session:
            yield session

    def override_service():
        with factory() as session:
            yield KnowledgeSubmissionService(session, settings, LocalDocumentParser())

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_submission_service] = override_service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/knowledge/submissions",
                files={"file": ("结构化.txt", "医学资料".encode(), "text/plain")},
                headers=auth_headers(owner.id),
            )
            assert created.status_code == 202
            submission_id = created.json()["submission_id"]

        with factory() as session:
            saved = session.get(KnowledgeSubmission, submission_id)
            assert saved is not None
            assert saved.preview_text == "医学资料"
            assert saved.preview_pages == 1
            assert saved.parse_warnings == []
            assert saved.parse_quality == {
                "status": "pass",
                "counts": {
                    "text": 1,
                    "table_like": 0,
                    "scanned_or_image": 0,
                },
                "page_results": [
                    {
                        "page": 1,
                        "kind": "text",
                        "text_chars": 4,
                        "image_count": 0,
                    }
                ],
            }
            assert session.scalar(
                select(func.count()).select_from(KnowledgeDocument)
            ) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_markdown_submission_gets_structured_preview_without_publication(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'markdown-submissions.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "markdown-submission-owner")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")

    def override_session():
        with factory() as session:
            yield session

    def override_service():
        with factory() as session:
            yield KnowledgeSubmissionService(session, settings, LocalDocumentParser())

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_submission_service] = override_service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/knowledge/submissions",
                files={
                    "file": (
                        "随访.md",
                        "# 随访记录\n\n| 项目 | 说明 |\n| --- | --- |\n| 血压 | 每日测量 |\n".encode(),
                        "application/pdf",
                    )
                },
                headers=auth_headers(owner.id),
            )
            assert created.status_code == 202
            submission_id = created.json()["submission_id"]

        with factory() as session:
            saved = session.get(KnowledgeSubmission, submission_id)
            assert saved is not None
            assert saved.status == "pending_review"
            assert "随访记录" in saved.preview_text
            assert saved.parse_quality["counts"]["title"] == 1
            assert saved.parse_quality["counts"]["table"] == 1
            assert session.scalar(
                select(func.count()).select_from(KnowledgeDocument)
            ) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_spoofed_submission_extension_fails_after_content_validation(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'spoofed-submissions.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "spoofed-submission-owner")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")

    def override_session():
        with factory() as session:
            yield session

    def override_service():
        with factory() as session:
            yield KnowledgeSubmissionService(session, settings, LocalDocumentParser())

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_submission_service] = override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/knowledge/submissions",
                files={"file": ("伪装.pdf", b"not a pdf", "application/pdf")},
                headers=auth_headers(owner.id),
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "DOCUMENT_PARSE_ERROR"
        with factory() as session:
            assert session.scalar(
                select(func.count()).select_from(KnowledgeSubmission)
            ) == 0
        assert not list(settings.submission_dir.glob("*"))
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
