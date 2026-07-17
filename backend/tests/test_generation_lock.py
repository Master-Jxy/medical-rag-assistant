"""会话生成锁的键、故障策略和生命周期测试。"""

import pytest

from app.core.config import Settings
from app.ports.distributed_lock import DistributedLockBackendUnavailable
from app.services.generation_lock_service import (
    ConversationGenerationInProgressError,
    GenerationLockService,
    GenerationLockUnavailableError,
)


class FakeLockBackend:
    def __init__(self, *, acquired=True, acquire_error=None, release_error=None):
        self.acquired = acquired
        self.acquire_error = acquire_error
        self.release_error = release_error
        self.acquire_calls = []
        self.release_calls = []

    def acquire_lock(self, key, owner_token, ttl_seconds):
        self.acquire_calls.append((key, owner_token, ttl_seconds))
        if self.acquire_error:
            raise self.acquire_error
        return self.acquired

    def release_lock(self, key, owner_token):
        self.release_calls.append((key, owner_token))
        if self.release_error:
            raise self.release_error
        return True


def build_service(backend):
    return GenerationLockService(
        backend,
        Settings(_env_file=None, generation_lock_ttl_seconds=321),
    )


def test_lock_key_is_hashed_and_release_uses_same_random_owner() -> None:
    backend = FakeLockBackend()
    service = build_service(backend)

    lease = service.acquire("private-user", "private-conversation")
    service.release(lease)

    key, owner, ttl = backend.acquire_calls[0]
    assert key.startswith("lock:generation:")
    assert "private-user" not in key
    assert "private-conversation" not in key
    assert len(owner) == 32
    assert ttl == 321
    assert backend.release_calls == [(key, owner)]


def test_occupied_lock_returns_stable_conflict() -> None:
    service = build_service(FakeLockBackend(acquired=False))

    with pytest.raises(ConversationGenerationInProgressError) as captured:
        service.acquire("user", "conversation")

    assert captured.value.status_code == 409
    assert captured.value.code == "CONVERSATION_GENERATION_IN_PROGRESS"


def test_unavailable_lock_fails_closed() -> None:
    service = build_service(
        FakeLockBackend(
            acquire_error=DistributedLockBackendUnavailable("unavailable")
        )
    )

    with pytest.raises(GenerationLockUnavailableError) as captured:
        service.acquire("user", "conversation")

    assert captured.value.status_code == 503
    assert captured.value.code == "GENERATION_LOCK_UNAVAILABLE"


def test_unknown_release_is_left_for_ttl_without_masking_result() -> None:
    backend = FakeLockBackend(
        release_error=DistributedLockBackendUnavailable("unavailable")
    )
    service = build_service(backend)
    lease = service.acquire("user", "conversation")

    service.release(lease)

    assert len(backend.release_calls) == 1
