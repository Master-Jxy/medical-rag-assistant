"""Redis 保护能力的状态、日志去重和恢复行为测试。"""

from fastapi.testclient import TestClient

from app.infrastructure.local_rate_limit import BoundedLocalRateLimitAdapter
from app.infrastructure.redis import RedisHealthStatus
from app.main import create_app
from app.ports.rate_limit import (
    RateLimitBackendUnavailable,
    RateLimitDecision,
)
from app.services.protection_observability import (
    GENERATION_LOCK,
    IDEMPOTENCY,
    RATE_LIMIT,
    UPLOAD_CONCURRENCY,
    ProtectionObservability,
)
from app.services.rate_limit_service import RateLimitService


class StubRedisInfrastructure:
    def __init__(self, status: RedisHealthStatus) -> None:
        self.status = status

    def health_status(self) -> RedisHealthStatus:
        return self.status

    def close(self) -> None:
        pass


class SequenceRateLimiter:
    def __init__(self, results: list[RateLimitDecision | Exception]) -> None:
        self.results = iter(results)

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_physical_redis_failure_projects_each_explicit_failure_policy() -> None:
    observability = ProtectionObservability(redis_configured=True)

    snapshot = observability.snapshot(RedisHealthStatus.DEGRADED)

    assert snapshot[RATE_LIMIT].policy == "local_fallback"
    assert snapshot[RATE_LIMIT].mode == "local_fallback"
    assert snapshot[UPLOAD_CONCURRENCY].mode == "local_fallback"
    assert snapshot[GENERATION_LOCK].policy == "fail_closed"
    assert snapshot[GENERATION_LOCK].mode == "unavailable"
    assert snapshot[IDEMPOTENCY].mode == "unavailable"


def test_repeated_failure_logs_once_and_recovery_is_observable(monkeypatch) -> None:
    observability = ProtectionObservability(redis_configured=True)
    warnings = []
    infos = []
    monkeypatch.setattr(
        "app.services.protection_observability.logger.warning",
        lambda message, **kwargs: warnings.append((message, kwargs)),
    )
    monkeypatch.setattr(
        "app.services.protection_observability.logger.info",
        lambda message, **kwargs: infos.append((message, kwargs)),
    )

    observability.record_failure(RATE_LIMIT, "SecretConnectionError")
    observability.record_failure(RATE_LIMIT, "SecretConnectionError")
    observability.record_success(RATE_LIMIT)
    observability.record_success(RATE_LIMIT)

    state = observability.snapshot(RedisHealthStatus.OK)[RATE_LIMIT]
    assert state.mode == "redis"
    assert state.success_events == 2
    assert state.failure_events == 2
    assert state.recovery_events == 1
    assert state.last_error_type is None
    assert len(warnings) == 1
    assert len(infos) == 1
    assert warnings[0][1]["extra"] == {
        "protection_feature": "rate_limit",
        "protection_policy": "local_fallback",
        "protection_mode": "local_fallback",
        "protection_error_type": "SecretConnectionError",
    }
    assert "redis://" not in repr(warnings)
    assert "password" not in repr(warnings).lower()


def test_rate_limit_fallback_and_recovery_update_shared_state(monkeypatch) -> None:
    observability = ProtectionObservability(redis_configured=True)
    warnings = []
    infos = []
    monkeypatch.setattr(
        "app.services.protection_observability.logger.warning",
        lambda message, **kwargs: warnings.append((message, kwargs)),
    )
    monkeypatch.setattr(
        "app.services.protection_observability.logger.info",
        lambda message, **kwargs: infos.append((message, kwargs)),
    )
    primary = SequenceRateLimiter(
        [
            RateLimitBackendUnavailable(),
            RateLimitBackendUnavailable(),
            RateLimitDecision(True, 60),
        ]
    )
    service = RateLimitService(
        primary,
        BoundedLocalRateLimitAdapter(10),
        observability,
    )

    assert service.consume("auth", "user-a", 10, 60).allowed is True
    assert service.consume("auth", "user-a", 10, 60).allowed is True
    assert service.consume("auth", "user-a", 10, 60).allowed is True

    state = observability.snapshot(RedisHealthStatus.OK)[RATE_LIMIT]
    assert state.failure_events == 2
    assert state.success_events == 1
    assert state.recovery_events == 1
    assert state.mode == "redis"
    assert len(warnings) == 1
    assert len(infos) == 1


def test_health_keeps_application_up_while_command_protection_is_unavailable() -> None:
    app = create_app(
        redis_infrastructure=StubRedisInfrastructure(RedisHealthStatus.OK)
    )
    app.state.protection_observability.record_failure(
        GENERATION_LOCK, "LockCommandError"
    )
    app.state.protection_observability.record_failure(
        IDEMPOTENCY, "CompletionStateMismatch"
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["dependencies"]["redis"]["status"] == "ok"
    generation = body["dependencies"]["protections"]["generation_lock"]
    idempotency = body["dependencies"]["protections"]["idempotency"]
    assert generation["mode"] == "unavailable"
    assert generation["last_error_type"] == "LockCommandError"
    assert idempotency["mode"] == "unavailable"
    assert idempotency["last_error_type"] == "CompletionStateMismatch"
