"""普通资料只进入隔离提交，不写公共文档或向量库。"""

import hashlib
from datetime import datetime, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
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
from app.modules.knowledge.web_snapshot import WebSnapshotError, WebSnapshotResult
from app.api.knowledge_submissions import get_submission_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def make_png_bytes() -> bytes:
    image = Image.new("RGB", (2, 2), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeParser:
    def parse(self, _path, _suffix):
        return ParsedPreview("解析预览", 1)


class FakeWebSnapshotFetcher:
    def __init__(self, content: bytes | None = None, error: Exception | None = None) -> None:
        self.content = content or "<html><body><h1>网页资料</h1><p>正文</p></body></html>".encode()
        self.error = error
        self.urls: list[str] = []

    async def fetch(self, url: str) -> WebSnapshotResult:
        self.urls.append(url)
        if self.error:
            raise self.error
        digest = hashlib.sha256(self.content).hexdigest()
        return WebSnapshotResult(
            original_url="https://example.com/article?token=secret",
            final_url="https://example.com/article",
            fetched_at=datetime.now(timezone.utc),
            mime_type="text/html",
            content_sha256=digest,
            content=self.content,
        )


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


def test_image_submission_waits_for_enrichment_and_withdraw_cleans_assets(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'image-submissions.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "image-submission-owner")
    settings = Settings(
        _env_file=None,
        submission_dir=tmp_path / "isolated",
        document_asset_dir=tmp_path / "assets",
    )

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
                files={"file": ("report.png", make_png_bytes(), "text/plain")},
                headers=auth_headers(owner.id),
            )
            assert created.status_code == 202
            assert created.json()["status"] == "pending_review"
            submission_id = created.json()["submission_id"]

        with factory() as session:
            saved = session.get(KnowledgeSubmission, submission_id)
            assert saved is not None
            assert saved.preview_text == ""
            assert saved.preview_pages == 1
            assert saved.parse_quality["enrichment"]["status"] == "waiting_enrichment"
            assert saved.parse_quality["counts"]["scanned_or_image"] == 1
            assert saved.parse_quality["assets"][0]["metadata"]["materialized"] is True
            assert session.scalar(
                select(func.count()).select_from(KnowledgeDocument)
            ) == 0
        assert (settings.document_asset_dir / "submissions" / submission_id).is_dir()

        with TestClient(app) as client:
            withdrawn = client.post(
                f"/api/v1/knowledge/submissions/{submission_id}/withdraw",
                headers=auth_headers(owner.id),
            )
            assert withdrawn.status_code == 200
            assert withdrawn.json()["status"] == "withdrawn"
        assert not (settings.document_asset_dir / "submissions" / submission_id).exists()
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


def test_web_snapshot_submission_creates_isolated_pending_review_and_metadata(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'web-submissions.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "web-submission-owner")
    other = create_test_user(factory, "web-submission-other")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")
    fetcher = FakeWebSnapshotFetcher()

    def override_session():
        with factory() as session:
            yield session

    def override_service():
        with factory() as session:
            yield KnowledgeSubmissionService(
                session,
                settings,
                LocalDocumentParser(),
                web_snapshot_fetcher=fetcher,
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_submission_service] = override_service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/knowledge/submissions/web-snapshots",
                json={"url": "https://example.com/article#drop"},
                headers=auth_headers(owner.id),
            )
            assert created.status_code == 202
            assert created.json()["status"] == "pending_review"
            submission_id = created.json()["submission_id"]
            assert client.get(
                "/api/v1/knowledge/submissions",
                headers=auth_headers(other.id),
            ).json()["total"] == 0

        with factory() as session:
            saved = session.get(KnowledgeSubmission, submission_id)
            assert saved is not None
            assert saved.original_name.startswith("网页快照-example.com")
            assert saved.stored_name == f"{submission_id}.html"
            assert saved.snapshot_original_url == "https://example.com/article?token=secret"
            assert saved.snapshot_final_url == "https://example.com/article"
            assert saved.snapshot_response_mime == "text/html"
            assert saved.snapshot_content_sha256 == saved.content_hash
            assert "网页资料" in saved.preview_text
            assert session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 0
        assert (settings.submission_dir / f"{submission_id}.html").is_file()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_web_snapshot_duplicate_and_fetch_failure_do_not_leave_orphan_file(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'web-failure.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "web-failure-owner")
    settings = Settings(_env_file=None, submission_dir=tmp_path / "isolated")
    content = b"<html><body>same</body></html>"
    digest = hashlib.sha256(content).hexdigest()
    settings.submission_dir.mkdir(parents=True)
    with factory() as session:
        session.add(
            KnowledgeSubmission(
                id="existing",
                submitter_id=owner.id,
                original_name="old.html",
                stored_name="existing.html",
                content_hash=digest,
                size_bytes=len(content),
                status="pending_review",
                parse_warnings=[],
            )
        )
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    def override_duplicate_service():
        with factory() as session:
            yield KnowledgeSubmissionService(
                session,
                settings,
                LocalDocumentParser(),
                web_snapshot_fetcher=FakeWebSnapshotFetcher(content=content),
            )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_submission_service] = override_duplicate_service
    try:
        with TestClient(app) as client:
            duplicate = client.post(
                "/api/v1/knowledge/submissions/web-snapshots",
                json={"url": "https://example.com/same"},
                headers=auth_headers(owner.id),
            )
            assert duplicate.status_code == 409
        assert sorted(path.name for path in settings.submission_dir.iterdir()) == []

        def override_failing_service():
            with factory() as session:
                yield KnowledgeSubmissionService(
                    session,
                    settings,
                    LocalDocumentParser(),
                    web_snapshot_fetcher=FakeWebSnapshotFetcher(
                        error=WebSnapshotError("网页快照抓取失败")
                    ),
                )

        app.dependency_overrides[get_submission_service] = override_failing_service
        with TestClient(app) as client:
            failed = client.post(
                "/api/v1/knowledge/submissions/web-snapshots",
                json={"url": "https://example.com/fail"},
                headers=auth_headers(owner.id),
            )
            assert failed.status_code == 422
        assert sorted(path.name for path in settings.submission_dir.iterdir()) == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
