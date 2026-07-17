"""Redis 基础设施测试：不需要真实 Redis，不接入限流或生成锁。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.infrastructure.redis import RedisHealthStatus, RedisInfrastructure
from app.main import create_app


class FakeRedisClient:
    def __init__(self, ping_results) -> None:
        self.ping_results = iter(ping_results)
        self.closed = False

    def ping(self) -> bool:
        result = next(self.ping_results)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self) -> None:
        self.closed = True


class FakeRateLimitRedisClient(FakeRedisClient):
    def __init__(self, eval_results) -> None:
        super().__init__([])
        self.eval_results = iter(eval_results)
        self.eval_calls = []

    def eval(self, script, numkeys, *keys_and_args):
        self.eval_calls.append((script, numkeys, keys_and_args))
        result = next(self.eval_results)
        if isinstance(result, Exception):
            raise result
        return result


class StubRedisInfrastructure:
    def __init__(self, status: RedisHealthStatus) -> None:
        self.status = status
        self.closed = False

    def health_status(self) -> RedisHealthStatus:
        return self.status

    def close(self) -> None:
        self.closed = True


def test_unconfigured_redis_is_disabled_without_creating_client() -> None:
    factory_calls = []
    infrastructure = RedisInfrastructure(
        Settings(_env_file=None, redis_url=None),
        client_factory=lambda *args, **kwargs: factory_calls.append((args, kwargs)),
    )

    assert infrastructure.health_status() is RedisHealthStatus.DISABLED
    assert factory_calls == []


def test_configured_redis_uses_bounded_timeouts_and_closes_client() -> None:
    client = FakeRedisClient([True])
    factory_calls = []

    def factory(*args, **kwargs):
        factory_calls.append((args, kwargs))
        return client

    infrastructure = RedisInfrastructure(
        Settings(
            _env_file=None,
            redis_url="redis://:secret@127.0.0.1:6379/0",
            redis_connect_timeout_seconds=0.25,
            redis_socket_timeout_seconds=0.4,
        ),
        client_factory=factory,
    )

    assert infrastructure.health_status() is RedisHealthStatus.OK
    assert factory_calls[0][0] == ("redis://:secret@127.0.0.1:6379/0",)
    assert factory_calls[0][1]["socket_connect_timeout"] == 0.25
    assert factory_calls[0][1]["socket_timeout"] == 0.4
    assert factory_calls[0][1]["retry_on_timeout"] is False

    infrastructure.close()
    assert client.closed is True


def test_runtime_failure_is_degraded_without_secret_and_next_check_recovers(
    monkeypatch,
) -> None:
    first_client = FakeRedisClient([True, ConnectionError("redis://:secret@host")])
    second_client = FakeRedisClient([True])
    clients = iter([first_client, second_client])
    infrastructure = RedisInfrastructure(
        Settings(_env_file=None, redis_url="redis://:secret@127.0.0.1:6379/0"),
        client_factory=lambda *args, **kwargs: next(clients),
    )
    warnings = []
    monkeypatch.setattr(
        "app.infrastructure.redis.logger.warning",
        lambda message, **kwargs: warnings.append((message, kwargs)),
    )

    assert infrastructure.health_status() is RedisHealthStatus.OK
    assert infrastructure.health_status() is RedisHealthStatus.DEGRADED
    assert infrastructure.health_status() is RedisHealthStatus.OK

    assert first_client.closed is True
    assert "secret" not in repr(warnings)
    assert warnings == [
        (
            "Redis health check failed",
            {"extra": {"redis_error_type": "ConnectionError"}},
        )
    ]


@pytest.mark.parametrize(
    ("redis_status", "expected"),
    [
        (RedisHealthStatus.OK, "ok"),
        (RedisHealthStatus.DISABLED, "disabled"),
        (RedisHealthStatus.DEGRADED, "degraded"),
    ],
)
def test_health_api_reports_redis_state_and_closes_on_shutdown(
    redis_status, expected
) -> None:
    infrastructure = StubRedisInfrastructure(redis_status)
    test_app = create_app(redis_infrastructure=infrastructure)

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    fallback_mode = "redis" if redis_status is RedisHealthStatus.OK else "local_fallback"
    strict_mode = "available" if redis_status is RedisHealthStatus.OK else "unavailable"
    empty_counters = {
        "success_events": 0,
        "failure_events": 0,
        "recovery_events": 0,
        "last_error_type": None,
    }
    assert response.json() == {
        "status": "ok",
        "dependencies": {
            "redis": {"status": expected},
            "protections": {
                "rate_limit": {
                    "policy": "local_fallback",
                    "mode": fallback_mode,
                    **empty_counters,
                },
                "upload_concurrency": {
                    "policy": "local_fallback",
                    "mode": fallback_mode,
                    **empty_counters,
                },
                "generation_lock": {
                    "policy": "fail_closed",
                    "mode": strict_mode,
                    **empty_counters,
                },
                "idempotency": {
                    "policy": "fail_closed",
                    "mode": strict_mode,
                    **empty_counters,
                },
            },
        },
    }
    assert infrastructure.closed is True


def test_redis_timeouts_must_be_positive_and_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, redis_connect_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, redis_socket_timeout_seconds=10)


def test_rate_limit_command_atomically_returns_count_and_ttl() -> None:
    client = FakeRateLimitRedisClient([[3, 47]])
    infrastructure = RedisInfrastructure(
        Settings(_env_file=None, redis_url="redis://127.0.0.1:6379/0"),
        client_factory=lambda *args, **kwargs: client,
    )

    decision = infrastructure.consume("safe-key", limit=2, window_seconds=60)

    assert decision.allowed is False
    assert decision.retry_after_seconds == 47
    script, numkeys, args = client.eval_calls[0]
    assert "INCR" in script
    assert "EXPIRE" in script
    assert numkeys == 1
    assert args == ("safe-key", 60)


def test_concurrency_commands_use_atomic_ttl_and_owner_checked_release() -> None:
    client = FakeRateLimitRedisClient([[1, 600], 1])
    infrastructure = RedisInfrastructure(
        Settings(_env_file=None, redis_url="redis://127.0.0.1:6379/0"),
        client_factory=lambda *args, **kwargs: client,
    )

    acquired = infrastructure.acquire("safe-upload-key", "owner-token", 1, 600)
    released = infrastructure.release("safe-upload-key", "owner-token")

    assert acquired.acquired is True
    assert acquired.retry_after_seconds == 600
    assert released is True
    acquire_script, acquire_numkeys, acquire_args = client.eval_calls[0]
    assert "ZREMRANGEBYSCORE" in acquire_script
    assert "ZADD" in acquire_script
    assert "EXPIRE" in acquire_script
    assert acquire_numkeys == 1
    assert acquire_args == ("safe-upload-key", "owner-token", 1, 600)
    release_script, release_numkeys, release_args = client.eval_calls[1]
    assert "ZREM" in release_script
    assert release_numkeys == 1
    assert release_args == ("safe-upload-key", "owner-token")


def test_distributed_lock_uses_ttl_and_atomic_owner_checked_release() -> None:
    client = FakeRateLimitRedisClient([1, 1, 0])
    infrastructure = RedisInfrastructure(
        Settings(_env_file=None, redis_url="redis://127.0.0.1:6379/0"),
        client_factory=lambda *args, **kwargs: client,
    )

    assert infrastructure.acquire_lock("safe-generation-key", "owner-a", 600) is True
    assert infrastructure.release_lock("safe-generation-key", "owner-a") is True
    assert infrastructure.release_lock("safe-generation-key", "old-owner") is False

    acquire_script, _, acquire_args = client.eval_calls[0]
    assert "SET" in acquire_script
    assert "NX" in acquire_script
    assert "EX" in acquire_script
    assert acquire_args == ("safe-generation-key", "owner-a", 600)
    release_script, _, release_args = client.eval_calls[1]
    assert "GET" in release_script
    assert "DEL" in release_script
    assert release_args == ("safe-generation-key", "owner-a")


def test_idempotency_commands_use_atomic_state_fingerprint_and_ttl() -> None:
    client = FakeRateLimitRedisClient(
        [
            ["started"],
            ["completed", "request-1", "conversation-1", "user-1", "assistant-1"],
            1,
            1,
        ]
    )
    infrastructure = RedisInfrastructure(
        Settings(_env_file=None, redis_url="redis://127.0.0.1:6379/0"),
        client_factory=lambda *args, **kwargs: client,
    )

    started = infrastructure.begin_idempotency("safe-key", "fingerprint", 600)
    completed = infrastructure.begin_idempotency("safe-key", "fingerprint", 600)
    stored = infrastructure.complete_idempotency(
        "safe-key",
        "fingerprint",
        request_id="request-1",
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        ttl_seconds=86400,
    )
    cleared = infrastructure.clear_idempotency("safe-key", "fingerprint")

    assert started.status.value == "started"
    assert completed.status.value == "completed"
    assert completed.assistant_message_id == "assistant-1"
    assert stored is True
    assert cleared is True
    begin_script, _, begin_args = client.eval_calls[0]
    assert "HSET" in begin_script
    assert "fingerprint" in begin_script
    assert "EXPIRE" in begin_script
    assert begin_args == ("safe-key", "fingerprint", 600)
    complete_script, _, complete_args = client.eval_calls[2]
    assert "state', 'completed" in complete_script
    assert "EXPIRE" in complete_script
    assert complete_args[-1] == 86400
    clear_script, _, clear_args = client.eval_calls[3]
    assert "HGET" in clear_script
    assert "DEL" in clear_script
    assert clear_args == ("safe-key", "fingerprint")
