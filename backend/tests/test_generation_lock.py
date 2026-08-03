"""会话生成锁的键、故障策略和生命周期测试。"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import AppError
from app.ports.concurrency_limit import ConcurrencyLimitDecision
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
        self.held_locks = {}
        self.slot_owners = {}
        self.slot_acquire_calls = []
        self.slot_release_calls = []

    def acquire(self, key, owner_token, limit, ttl_seconds):
        owners = self.slot_owners.setdefault(key, set())
        self.slot_acquire_calls.append((key, owner_token, limit, ttl_seconds))
        if len(owners) >= limit:
            return ConcurrencyLimitDecision(False, ttl_seconds)
        owners.add(owner_token)
        return ConcurrencyLimitDecision(True, ttl_seconds)

    def release(self, key, owner_token):
        self.slot_release_calls.append((key, owner_token))
        owners = self.slot_owners.get(key, set())
        if owner_token not in owners:
            return False
        owners.remove(owner_token)
        return True

    def acquire_lock(self, key, owner_token, ttl_seconds):
        self.acquire_calls.append((key, owner_token, ttl_seconds))
        if self.acquire_error:
            raise self.acquire_error
        if not self.acquired or key in self.held_locks:
            return False
        self.held_locks[key] = owner_token
        return True

    def release_lock(self, key, owner_token):
        self.release_calls.append((key, owner_token))
        if self.release_error:
            raise self.release_error
        if self.held_locks.get(key) != owner_token:
            return False
        self.held_locks.pop(key)
        return True


def build_service(backend):
    return GenerationLockService(
        backend,
        Settings(
            _env_file=None,
            generation_lock_ttl_seconds=321,
            generation_active_run_limit=2,
            generation_lock_cleanup_grace_seconds=30,
            agent_run_timeout_seconds=120,
        ),
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


def test_agent_thread_lock_uses_an_independent_hashed_namespace() -> None:
    backend = FakeLockBackend()
    service = build_service(backend)

    conversation_lease = service.acquire("same-user", "same-resource")
    agent_lease = service.acquire_agent("same-user", "same-resource")

    assert conversation_lease.key.startswith("lock:generation:")
    assert agent_lease.key.startswith("lock:generation:agent-thread:")
    assert agent_lease.key != conversation_lease.key
    assert "same-user" not in agent_lease.key
    assert "same-resource" not in agent_lease.key


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


def test_user_active_run_slots_are_shared_by_rag_and_agent() -> None:
    backend = FakeLockBackend()
    service = build_service(backend)

    rag_lease = service.acquire("same-user", "conversation-a")
    agent_lease = service.acquire_agent("same-user", "thread-b")

    with pytest.raises(AppError) as captured:
        service.acquire("same-user", "conversation-c")

    assert captured.value.code == "USER_ACTIVE_RUN_LIMIT_REACHED"
    assert captured.value.status_code == 429
    assert len(next(iter(backend.slot_owners.values()))) == 2

    service.release(rag_lease)
    replacement = service.acquire("same-user", "conversation-c")
    service.release(replacement)
    service.release(agent_lease)
    assert next(iter(backend.slot_owners.values())) == set()


def test_same_conversation_conflict_releases_the_extra_user_slot() -> None:
    backend = FakeLockBackend()
    service = build_service(backend)
    held = service.acquire("same-user", "same-conversation")

    with pytest.raises(ConversationGenerationInProgressError):
        service.acquire("same-user", "same-conversation")

    assert len(next(iter(backend.slot_owners.values()))) == 1
    service.release(held)


def test_generation_configuration_rejects_unsafe_ttl_and_invalid_slot_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            generation_lock_ttl_seconds=120,
            generation_lock_cleanup_grace_seconds=30,
            agent_run_timeout_seconds=120,
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, generation_active_run_limit=5)
