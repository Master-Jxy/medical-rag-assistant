"""认证限流回归：验证 429 契约、可信代理边界和 Redis 故障兜底。"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import register_exception_handlers
from app.infrastructure.local_rate_limit import BoundedLocalRateLimitAdapter
from app.modules.auth.dependencies import get_client_address
from app.modules.auth.rate_limit import (
    AuthRateLimitExceededError,
    AuthRateLimitService,
)
from app.ports.rate_limit import RateLimitBackendUnavailable, RateLimitDecision
from app.services.rate_limit_service import RateLimitService


class UnavailableRateLimiter:
    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        raise RateLimitBackendUnavailable()


class RecordingRateLimiter:
    def __init__(self, decisions: list[RateLimitDecision]) -> None:
        self.decisions = iter(decisions)
        self.calls: list[tuple[str, int, int]] = []

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        self.calls.append((key, limit, window_seconds))
        return next(self.decisions)


def build_settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        auth_register_rate_limit=2,
        auth_register_rate_window_seconds=60,
        auth_login_rate_limit=3,
        auth_login_rate_window_seconds=30,
        **overrides,
    )


def test_register_and_login_use_separate_hashed_keys_and_policies() -> None:
    primary = RecordingRateLimiter([RateLimitDecision(True, 60), RateLimitDecision(True, 30)])
    service = AuthRateLimitService(
        RateLimitService(primary, UnavailableRateLimiter()), build_settings()
    )

    service.check_register("203.0.113.9")
    service.check_login("203.0.113.9")

    register_call, login_call = primary.calls
    assert register_call[1:] == (2, 60)
    assert login_call[1:] == (3, 30)
    assert register_call[0] != login_call[0]
    assert "203.0.113.9" not in repr(primary.calls)


def test_redis_failure_uses_expiring_local_limit_and_returns_stable_429() -> None:
    now = [100.0]
    fallback = BoundedLocalRateLimitAdapter(8, clock=lambda: now[0])
    service = AuthRateLimitService(
        RateLimitService(UnavailableRateLimiter(), fallback), build_settings()
    )

    service.check_register("198.51.100.7")
    service.check_register("198.51.100.7")
    with pytest.raises(AuthRateLimitExceededError) as caught:
        service.check_register("198.51.100.7")

    assert caught.value.code == "AUTH_RATE_LIMITED"
    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "60"}

    now[0] += 61
    service.check_register("198.51.100.7")


def test_local_fallback_denies_new_keys_when_capacity_is_full() -> None:
    fallback = BoundedLocalRateLimitAdapter(1, clock=lambda: 10.0)
    assert fallback.consume("first", 10, 60).allowed is True

    decision = fallback.consume("second", 10, 60)

    assert decision.allowed is False
    assert decision.retry_after_seconds == 60


@pytest.mark.parametrize(
    ("trusted_proxies", "expected"),
    [([], "10.0.0.1"), (["10.0.0.1"], "203.0.113.4")],
)
def test_forwarded_address_is_only_used_for_a_trusted_proxy(
    trusted_proxies: list[str], expected: str
) -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"203.0.113.4, 10.0.0.1")],
            "client": ("10.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )
    settings = build_settings(trusted_proxy_ips=trusted_proxies)

    assert get_client_address(request, settings) == expected


def test_rate_limit_error_response_contains_request_id_and_retry_after() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/limited")
    def limited():
        raise AuthRateLimitExceededError(17)

    response = TestClient(app).get("/limited")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json()["error"] == {
        "code": "AUTH_RATE_LIMITED",
        "message": "操作过于频繁，请稍后再试",
    }
    assert response.json()["request_id"]
