"""请求幂等端口：Redis 只保存短期状态和最终消息资源标识。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class IdempotencyBackendUnavailable(RuntimeError):
    """无法确认幂等记录状态。"""


class IdempotencyStatus(StrEnum):
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class IdempotencyRecord:
    status: IdempotencyStatus
    request_id: str | None = None
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None


class IdempotencyPort(Protocol):
    def begin_idempotency(
        self, key: str, fingerprint: str, ttl_seconds: int
    ) -> IdempotencyRecord: ...

    def complete_idempotency(
        self,
        key: str,
        fingerprint: str,
        *,
        request_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        ttl_seconds: int,
    ) -> bool: ...

    def clear_idempotency(self, key: str, fingerprint: str) -> bool: ...
