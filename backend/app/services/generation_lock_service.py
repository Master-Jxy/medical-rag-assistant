"""会话生成锁：同一用户的同一会话只允许一个回答生成。"""

import hashlib
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AppError
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


@dataclass(frozen=True)
class GenerationLockLease:
    key: str
    owner_token: str


class GenerationLockService:
    """生成业务键并采用 fail-closed 策略获取 Redis 锁。"""

    def __init__(
        self,
        backend: DistributedLockPort,
        settings: Settings,
        observability: ProtectionObservability | None = None,
    ) -> None:
        self.backend = backend
        self.ttl_seconds = settings.generation_lock_ttl_seconds
        self.observability = observability or ProtectionObservability(
            redis_configured=True
        )

    def acquire(self, user_id: str, conversation_id: str) -> GenerationLockLease:
        subject = hashlib.sha256(
            f"{user_id}:{conversation_id}".encode("utf-8")
        ).hexdigest()
        lease = GenerationLockLease(
            key=f"lock:generation:{subject}",
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
            raise GenerationLockUnavailableError() from exc
        self.observability.record_success(GENERATION_LOCK)
        if not acquired:
            raise ConversationGenerationInProgressError()
        return lease

    def release(self, lease: GenerationLockLease) -> None:
        """释放失败时保留 TTL 兜底，不能误删或掩盖已生成的回答。"""
        try:
            released = self.backend.release_lock(lease.key, lease.owner_token)
        except DistributedLockBackendUnavailable as exc:
            self.observability.record_failure(GENERATION_LOCK, type(exc).__name__)
            return
        if not released:
            self.observability.record_failure(GENERATION_LOCK, "OwnershipMismatch")


def get_generation_lock_service(request: Request) -> GenerationLockService:
    return request.app.state.generation_lock_service
