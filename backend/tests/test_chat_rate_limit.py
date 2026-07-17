"""聊天限流测试：用户隔离、四个入口和 SSE 响应前 429。"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import get_db_session
from app.infrastructure.local_rate_limit import BoundedLocalRateLimitAdapter
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.ports.rate_limit import RateLimitBackendUnavailable, RateLimitDecision
from app.services.chat_rate_limit_service import (
    ChatRateLimitExceededError,
    ChatRateLimitService,
    get_chat_rate_limit_service,
)
from app.services.rag_service import get_rag_service
from app.services.rate_limit_service import RateLimitService


class UnavailableRateLimiter:
    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        raise RateLimitBackendUnavailable()


class RecordingRateLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        self.calls.append((key, limit, window_seconds))
        return RateLimitDecision(True, window_seconds)


class RejectChatRateLimiter:
    def __init__(self) -> None:
        self.user_ids: list[str] = []

    def check(self, user_id: str) -> None:
        self.user_ids.append(user_id)
        raise ChatRateLimitExceededError(19)


class NeverCalledRagService:
    def ask(self, *args, **kwargs):
        raise AssertionError("限流请求不应调用 RAG")

    def stream_ask(self, *args, **kwargs):
        raise AssertionError("限流请求不应调用流式 RAG")


TEST_USER = UserResponse(
    id="chat-rate-user",
    email="chat-rate@example.com",
    display_name="限流测试用户",
    is_active=True,
    role="user",
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


def chat_settings(limit: int = 10) -> Settings:
    return Settings(
        _env_file=None,
        chat_rate_limit=limit,
        chat_rate_window_seconds=60,
    )


def test_chat_policy_uses_hashed_user_key_and_explicit_window() -> None:
    primary = RecordingRateLimiter()
    service = ChatRateLimitService(
        RateLimitService(primary, UnavailableRateLimiter()), chat_settings()
    )

    service.check("private-user-id")

    key, limit, window = primary.calls[0]
    assert key.startswith("medical-rag:chat:user:")
    assert "private-user-id" not in key
    assert (limit, window) == (10, 60)


def test_different_users_have_independent_local_fallback_quotas() -> None:
    fallback = BoundedLocalRateLimitAdapter(8, clock=lambda: 100.0)
    service = ChatRateLimitService(
        RateLimitService(UnavailableRateLimiter(), fallback), chat_settings(limit=1)
    )

    service.check("user-a")
    service.check("user-b")
    with pytest.raises(ChatRateLimitExceededError) as caught:
        service.check("user-a")

    assert caught.value.code == "CHAT_RATE_LIMITED"
    assert caught.value.headers == {"Retry-After": "60"}


def test_all_chat_routes_return_json_429_before_rag_or_sse_starts() -> None:
    rejecting_limiter = RejectChatRateLimiter()
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_chat_rate_limit_service] = lambda: rejecting_limiter
    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_rag_service] = NeverCalledRagService
    try:
        with TestClient(app) as client:
            responses = [
                client.post(
                    "/api/v1/chat",
                    json={"question": "普通问答", "top_k": 2},
                ),
                client.post(
                    "/api/v1/chat/stream",
                    json={"question": "普通流式问答", "top_k": 2},
                ),
                client.post(
                    "/api/v1/conversations/conversation-id/chat",
                    json={"question": "会话问答", "top_k": 2},
                    headers={"Idempotency-Key": "rate-limit-normal"},
                ),
                client.post(
                    "/api/v1/conversations/conversation-id/chat/stream",
                    json={"question": "会话流式问答", "top_k": 2},
                    headers={"Idempotency-Key": "rate-limit-stream"},
                ),
            ]
    finally:
        app.dependency_overrides.clear()

    for response in responses:
        assert response.status_code == 429
        assert response.headers["retry-after"] == "19"
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"] == {
            "code": "CHAT_RATE_LIMITED",
            "message": "问答请求过于频繁，请稍后再试",
        }
        assert response.json()["request_id"]

    assert rejecting_limiter.user_ids == [TEST_USER.id] * 4
