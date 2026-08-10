"""Stage 25.3 RAG image message, SSE and history tests using Fake vision."""

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import MediaAsset, MessageAttachment, ModelUsageRecord, VisionObservationRecord
from app.modules.auth.tokens import get_token_service
from app.modules.rag.ports import ModelUsage
from app.schemas.chat import SourceItem
from app.services.generation_lock_service import GenerationLockLease, get_generation_lock_service
from app.services.idempotency_service import get_idempotency_service
from app.services.rag_service import get_rag_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.idempotency_helpers import AllowingIdempotency


class AllowingLock:
    def acquire(self, user_id, conversation_id):
        return GenerationLockLease("stage25-lock", "owner")

    def release(self, lease):
        del lease


class ImageAwareRag:
    model_name = "fake-chat"

    def __init__(self) -> None:
        self.questions: list[str] = []

    def ask_with_usage(self, question, top_k, history=None):
        self.questions.append(question)
        assert "结构化观察" in question and "白细胞计数" in question
        return "图片显示的是测试报告；知识库说明如下。", [SourceItem(file_name="指南.pdf", content="知识库依据")], ModelUsage.actual(30, 10)

    def stream_ask(self, question, top_k, history=None):
        self.questions.append(question)
        assert "结构化观察" in question and "白细胞计数" in question
        yield {"event": "token", "data": {"content": "流式图片回答"}}
        yield {"event": "model_usage", "data": ModelUsage.actual(30, 10).as_dict()}
        yield {"event": "sources", "data": {"sources": []}}


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 20), "white").save(output, format="PNG")
    return output.getvalue()


def setup(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'rag-images.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "rag-image-user")
    settings = Settings(
        _env_file=None, media_asset_dir=tmp_path / "media",
        vision_chat_enabled=True, vision_provider="fake", quota_policy_mode="off",
    )

    def override_session():
        with factory() as session:
            yield session

    rag = ImageAwareRag()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_generation_lock_service] = lambda: AllowingLock()
    app.dependency_overrides[get_idempotency_service] = lambda: AllowingIdempotency()
    app.dependency_overrides[get_rag_service] = lambda: rag
    return engine, factory, user, rag


def upload(client: TestClient, headers: dict) -> str:
    response = client.post(
        "/api/v1/media/assets",
        files={"file": ("report.png", png_bytes(), "image/png")},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_pure_image_rag_persists_attachment_observation_and_combined_usage(tmp_path) -> None:
    engine, factory, user, rag = setup(tmp_path)
    try:
        with TestClient(app) as client:
            headers = auth_headers(user.id)
            asset_id = upload(client, headers)
            conversation_id = client.post("/api/v1/conversations", json={"title": "新对话"}, headers=headers).json()["id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "", "attachment_ids": [asset_id]},
                headers={**headers, "Idempotency-Key": "image-rag"},
            )
            assert response.status_code == 200 and rag.questions
            detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers).json()
            assert detail["title"] == "图片问答"
            assert detail["messages"][0]["attachments"][0]["media_asset_id"] == asset_id
            assert detail["messages"][1]["vision_observations"][0]["observation"]["image_type"] == "medical_report"
            assert detail["messages"][1]["usage"]["total_tokens"] == 208
            with factory() as session:
                assert len(list(session.scalars(select(MessageAttachment)))) == 1
                assert len(list(session.scalars(select(VisionObservationRecord)))) == 1
                assert {row.surface for row in session.scalars(select(ModelUsageRecord))} == {"vision_rag", "rag"}
                asset = session.get(MediaAsset, asset_id)
                stored_path = tmp_path / "media" / asset.storage_key
                assert stored_path.exists()
            deleted = client.delete(f"/api/v1/conversations/{conversation_id}", headers=headers)
            assert deleted.status_code == 200
            with factory() as session:
                assert session.get(MediaAsset, asset_id).status == "deleted"
            assert not stored_path.exists()
    finally:
        app.dependency_overrides.clear(); engine.dispose()


def test_image_rag_stream_emits_observation_before_tokens(tmp_path) -> None:
    engine, factory, user, _rag = setup(tmp_path)
    try:
        with TestClient(app) as client:
            headers = auth_headers(user.id)
            asset_id = upload(client, headers)
            conversation_id = client.post("/api/v1/conversations", json={"title": "新对话"}, headers=headers).json()["id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "这张图表示什么？", "attachment_ids": [asset_id]},
                headers={**headers, "Idempotency-Key": "image-rag-stream"},
            )
            assert response.status_code == 200
            assert "event: vision_observations" in response.text
            assert response.text.index("event: vision_observations") < response.text.index("event: token")
            assert "event: done" in response.text
            with factory() as session:
                overview = session.scalar(select(VisionObservationRecord))
                merged = dict(overview.observation_json)
                merged["quality_summary"] = {
                    "route_kind": "ocr_mode",
                    "quality_status": "pass",
                    "quality_codes": ["OCR_MODE_APPLIED"],
                }
                overview.observation_json = merged
                overview.route_kind = "ocr_mode"
                overview.quality_status = "pass"
                overview.quality_codes = ["OCR_MODE_APPLIED"]
                session.add(VisionObservationRecord(
                    media_asset_id=overview.media_asset_id,
                    user_id=overview.user_id,
                    assistant_message_id=overview.assistant_message_id,
                    observation_scope_id=overview.observation_scope_id,
                    kind="report_extract",
                    focus_instruction_hash="ocr:history-filter-test",
                    model_name="fake-chat-ocr",
                    status="completed",
                    sequence_no=2,
                    route_kind="ocr_mode",
                    quality_status="pass",
                    quality_codes=[],
                    provider_call_count=1,
                    observation_json={
                        "image_type": "document",
                        "summary": "internal OCR extraction",
                        "visible_text": ["INTERNAL ONLY"],
                        "quality_summary": {
                            "route_kind": "ocr_mode",
                            "quality_status": "pass",
                            "quality_codes": [],
                        },
                    },
                ))
                session.commit()
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            ).json()
            history = detail["messages"][1]["vision_observations"]
            assert len(history) == 1
            assert history[0]["kind"] == "overview"
            assert history[0]["observation"]["quality_summary"] == {
                "route_kind": "ocr_mode",
                "quality_status": "pass",
                "quality_codes": ["OCR_MODE_APPLIED"],
            }
            with factory() as session:
                assert len(list(session.scalars(select(VisionObservationRecord)))) == 2
    finally:
        app.dependency_overrides.clear(); engine.dispose()
