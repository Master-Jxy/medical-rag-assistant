"""基础接口测试；使用假 RAG 服务，不调用真实模型，不产生费用。"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app, create_app
from app.core.exceptions import RagServiceError
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.infrastructure.redis import RedisHealthStatus
from app.schemas.chat import SourceItem
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.document_service import get_document_service
from app.services.chat_rate_limit_service import get_chat_rate_limit_service
from app.services.rag_service import get_rag_service


class FakeRagService:
    """测试替身：固定返回结果，用来单独验证 HTTP 接口层。"""

    def ask(self, question: str, top_k: int) -> tuple[str, list[SourceItem]]:
        assert question == "什么是测试问题？"
        assert top_k == 2
        return (
            "这是测试回答。",
            [SourceItem(file_name="测试资料.txt", page=None, content="测试引用内容")],
        )

    def stream_ask(self, question: str, top_k: int):
        assert question == "什么是测试问题？"
        assert top_k == 2
        yield {"event": "token", "data": {"content": "这是"}}
        yield {"event": "token", "data": {"content": "流式回答。"}}
        yield {
            "event": "sources",
            "data": {
                "sources": [
                    {
                        "file_name": "测试资料.txt",
                        "page": None,
                        "content": "测试引用内容",
                    }
                ]
            },
        }


class FailingStreamRagService:
    def stream_ask(self, question: str, top_k: int):
        raise RagServiceError("测试流式错误")
        yield


class FakeDocumentService:
    async def process_upload(self, user_id, upload_file) -> DocumentUploadResponse:
        assert user_id == "test-user-id"
        assert upload_file.filename == "资料.txt"
        await upload_file.close()
        return DocumentUploadResponse(
            document_id="test-document-id",
            file_name="资料.txt",
            file_size=12,
            chunk_count=2,
            is_system=False,
            can_delete=True,
            created_at=datetime.now(timezone.utc),
        )

    def list_documents(self, user_id) -> DocumentListResponse:
        assert user_id == "test-user-id"
        item = DocumentItem(
            document_id="test-document-id",
            file_name="资料.txt",
            file_size=12,
            chunk_count=2,
            is_system=False,
            can_delete=True,
            created_at=datetime.now(timezone.utc),
        )
        return DocumentListResponse(documents=[item], total=1)

    def delete_document(self, user_id: str, document_id: str) -> DocumentDeleteResponse:
        assert user_id == "test-user-id"
        assert document_id == "test-document-id"
        return DocumentDeleteResponse(document_id=document_id)


TEST_USER = UserResponse(
    id="test-user-id",
    email="test-user@example.com",
    display_name="测试用户",
    is_active=True,
    role="user",
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


class AllowAllChatRateLimiter:
    def check(self, user_id: str) -> None:
        assert user_id == TEST_USER.id


@pytest.fixture
def authenticated_chat():
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_chat_rate_limit_service] = AllowAllChatRateLimiter
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_health_check() -> None:
    class DisabledRedis:
        def health_status(self):
            return RedisHealthStatus.DISABLED

        def close(self):
            pass

    with TestClient(create_app(redis_infrastructure=DisabledRedis())) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["redis"] == {"status": "disabled"}
    assert body["dependencies"]["protections"]["rate_limit"]["mode"] == (
        "local_fallback"
    )
    assert body["dependencies"]["protections"]["generation_lock"]["mode"] == (
        "unavailable"
    )


def test_vue_development_origin_is_allowed_by_cors() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_chat_returns_answer_and_sources_without_real_model_call(authenticated_chat) -> None:
    app.dependency_overrides[get_rag_service] = lambda: FakeRagService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/chat",
                json={"question": "什么是测试问题？", "top_k": 2},
            )
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["answer"] == "这是测试回答。"
    assert body["sources"][0]["file_name"] == "测试资料.txt"
    assert body["request_id"]
    assert "不构成医疗建议" in body["disclaimer"]


def test_stream_chat_returns_tokens_sources_and_done_events(authenticated_chat) -> None:
    app.dependency_overrides[get_rag_service] = lambda: FakeRagService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/chat/stream",
                json={"question": "什么是测试问题？", "top_k": 2},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: token") == 2
    assert "这是" in response.text
    assert "event: sources" in response.text
    assert "测试资料.txt" in response.text
    assert "event: done" in response.text
    assert "request_id" in response.text


def test_stream_chat_rejects_blank_question_before_stream_starts(authenticated_chat) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={"question": "   ", "top_k": 2},
        )

    assert response.status_code == 422


def test_stream_chat_converts_runtime_error_to_safe_sse_event(authenticated_chat) -> None:
    app.dependency_overrides[get_rag_service] = lambda: FailingStreamRagService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/chat/stream",
                json={"question": "触发错误", "top_k": 2},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "RAG_SERVICE_ERROR" in response.text
    assert "测试流式错误" in response.text
    assert "Traceback" not in response.text


def test_chat_rejects_blank_question(authenticated_chat) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"question": "   ", "top_k": 4},
        )

    assert response.status_code == 422


def test_chat_rejects_invalid_top_k(authenticated_chat) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"question": "有效问题", "top_k": 11},
        )

    assert response.status_code == 422


def test_plain_chat_requires_authentication() -> None:
    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v1/chat",
                json={"question": "有效问题", "top_k": 2},
            ),
            client.post(
                "/api/v1/chat/stream",
                json={"question": "有效问题", "top_k": 2},
            ),
        ]

    for response in responses:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_AUTH_TOKEN"


def test_document_upload_endpoint() -> None:
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/documents",
                files={"file": ("资料.txt", b"test content", "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["document_id"] == "test-document-id"
    assert response.json()["status"] == "ready"


def test_document_list_and_delete_endpoints() -> None:
    app.dependency_overrides[get_document_service] = lambda: FakeDocumentService()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    try:
        with TestClient(app) as client:
            list_response = client.get("/api/v1/documents")
            delete_response = client.delete("/api/v1/documents/test-document-id")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "文档已删除"
