"""会话生成锁：同一用户的同一会话只允许一个回答生成。"""

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AppError
from app.ports.concurrency_limit import (
    ConcurrencyLimitBackendUnavailable,
    ConcurrencyLimitPort,
)
from app.ports.distributed_lock import (
    DistributedLockBackendUnavailable,
    DistributedLockPort,
)
from app.services.protection_observability import (
    GENERATION_LOCK,
    ProtectionObservability,
)


class ConversationGenerationInProgressError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "该会话正在生成回答，请等待当前回答结束",
            code="CONVERSATION_GENERATION_IN_PROGRESS",
            status_code=409,
        )


class GenerationLockUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "回答保护服务暂时不可用，请稍后重试",
            code="GENERATION_LOCK_UNAVAILABLE",
            status_code=503,
        )


class UserActiveRunLimitReachedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "同时生成的会话已达上限，请等待一个回答结束后重试",
            code="USER_ACTIVE_RUN_LIMIT_REACHED",
            status_code=429,
        )


class GenerationProtectionPort(
    DistributedLockPort,
    ConcurrencyLimitPort,
    Protocol,
):
    """生成保护需要同一基础设施同时提供容量占位和互斥锁。"""


@dataclass(frozen=True)
class GenerationLockLease:
    key: str
    owner_token: str
    slot_key: str | None = None
    slot_owner_token: str | None = None


class GenerationLockService:
    """生成业务键并采用 fail-closed 策略获取 Redis 锁。"""

    def __init__(
        self,
        backend: GenerationProtectionPort,
        settings: Settings,
        observability: ProtectionObservability | None = None,
    ) -> None:
        self.backend = backend
        self.slot_backend = backend
        self.ttl_seconds = settings.generation_lock_ttl_seconds
        self.active_run_limit = settings.generation_active_run_limit
        self.observability = observability or ProtectionObservability(
            redis_configured=True
        )

    def acquire(self, user_id: str, conversation_id: str) -> GenerationLockLease:
        return self._acquire(user_id, conversation_id, namespace=None)

    def acquire_agent(self, user_id: str, thread_id: str) -> GenerationLockLease:
        return self._acquire(user_id, thread_id, namespace="agent-thread")

    def _acquire(
        self,
        user_id: str,
        resource_id: str,
        *,
        namespace: str | None,
    ) -> GenerationLockLease:
        slot_key, slot_owner_token = self._acquire_user_slot(user_id)
        subject = hashlib.sha256(
            f"{user_id}:{resource_id}".encode("utf-8")
        ).hexdigest()
        lease = GenerationLockLease(
            key=(
                f"lock:generation:{namespace}:{subject}"
                if namespace
                else f"lock:generation:{subject}"
            ),
            owner_token=uuid4().hex,
        )
        try:
            acquired = self.backend.acquire_lock(
                lease.key,
                lease.owner_token,
                self.ttl_seconds,
            )
        except DistributedLockBackendUnavailable as exc:
            self.observability.record_failure(GENERATION_LOCK, type(exc).__name__)
            self._release_user_slot(slot_key, slot_owner_token)
            raise GenerationLockUnavailableError() from exc
        self.observability.record_success(GENERATION_LOCK)
        if not acquired:
            self._release_user_slot(slot_key, slot_owner_token)
            raise ConversationGenerationInProgressError()
        return GenerationLockLease(
            key=lease.key,
            owner_token=lease.owner_token,
            slot_key=slot_key,
            slot_owner_token=slot_owner_token,
        )

    def _acquire_user_slot(self, user_id: str) -> tuple[str, str]:
        subject = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        key = f"slot:generation:user:{subject}"
        owner_token = uuid4().hex
        try:
            decision = self.slot_backend.acquire(
                key,
                owner_token,
                self.active_run_limit,
                self.ttl_seconds,
            )
        except ConcurrencyLimitBackendUnavailable as exc:
            self.observability.record_failure(GENERATION_LOCK, type(exc).__name__)
            raise GenerationLockUnavailableError() from exc
        self.observability.record_success(GENERATION_LOCK)
        if not decision.acquired:
            raise UserActiveRunLimitReachedError()
        return key, owner_token

    def release(self, lease: GenerationLockLease) -> None:
        """释放失败时保留 TTL 兜底，不能误删或掩盖已生成的回答。"""
        try:
            released = self.backend.release_lock(lease.key, lease.owner_token)
        except DistributedLockBackendUnavailable as exc:
            self.observability.record_failure(GENERATION_LOCK, type(exc).__name__)
        else:
            if not released:
                self.observability.record_failure(
                    GENERATION_LOCK, "OwnershipMismatch"
                )
        if lease.slot_key is not None and lease.slot_owner_token is not None:
            self._release_user_slot(lease.slot_key, lease.slot_owner_token)

    def _release_user_slot(self, key: str, owner_token: str) -> None:
        try:
            released = self.slot_backend.release(key, owner_token)
        except ConcurrencyLimitBackendUnavailable as exc:
            self.observability.record_failure(GENERATION_LOCK, type(exc).__name__)
            return
        if not released:
            self.observability.record_failure(GENERATION_LOCK, "OwnershipMismatch")


def get_generation_lock_service(request: Request) -> GenerationLockService:
    return request.app.state.generation_lock_service
