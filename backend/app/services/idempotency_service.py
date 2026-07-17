"""会话问答幂等策略：生成安全键并把 Redis 故障转换为稳定业务错误。"""

import hashlib
from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AppError
from app.ports.idempotency import (
    IdempotencyBackendUnavailable,
    IdempotencyPort,
    IdempotencyRecord,
    IdempotencyStatus,
)
from app.services.protection_observability import (
    IDEMPOTENCY,
    ProtectionObservability,
)


class IdempotencyRequestInProgressError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "相同请求正在处理中，请等待当前请求结束",
            code="IDEMPOTENCY_REQUEST_IN_PROGRESS",
            status_code=409,
        )


class IdempotencyKeyReusedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "该幂等键已用于其他请求，请生成新的幂等键",
            code="IDEMPOTENCY_KEY_REUSED",
            status_code=409,
        )


class IdempotencyUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "请求去重服务暂时不可用，请稍后重试",
            code="IDEMPOTENCY_UNAVAILABLE",
            status_code=503,
        )


@dataclass(frozen=True)
class IdempotencyClaim:
    key: str
    fingerprint: str
    completed_record: IdempotencyRecord | None = None


class IdempotencyService:
    def __init__(
        self,
        backend: IdempotencyPort,
        settings: Settings,
        observability: ProtectionObservability | None = None,
    ) -> None:
        self.backend = backend
        self.in_progress_ttl_seconds = settings.idempotency_in_progress_ttl_seconds
        self.result_ttl_seconds = settings.idempotency_result_ttl_seconds
        self.observability = observability or ProtectionObservability(
            redis_configured=True
        )

    def begin(
        self,
        user_id: str,
        endpoint: str,
        client_request_id: str,
        conversation_id: str,
        question: str,
        top_k: int,
    ) -> IdempotencyClaim:
        subject = hashlib.sha256(
            f"{user_id}:{endpoint}:{client_request_id}".encode("utf-8")
        ).hexdigest()
        fingerprint = hashlib.sha256(
            f"{conversation_id}\0{question}\0{top_k}".encode("utf-8")
        ).hexdigest()
        key = f"idempotency:conversation-chat:{subject}"
        try:
            record = self.backend.begin_idempotency(
                key, fingerprint, self.in_progress_ttl_seconds
            )
        except IdempotencyBackendUnavailable as exc:
            self.observability.record_failure(IDEMPOTENCY, type(exc).__name__)
            raise IdempotencyUnavailableError() from exc
        self.observability.record_success(IDEMPOTENCY)

        if record.status is IdempotencyStatus.IN_PROGRESS:
            raise IdempotencyRequestInProgressError()
        if record.status is IdempotencyStatus.CONFLICT:
            raise IdempotencyKeyReusedError()
        if record.status is IdempotencyStatus.COMPLETED:
            return IdempotencyClaim(key, fingerprint, record)
        return IdempotencyClaim(key, fingerprint)

    def complete(
        self,
        claim: IdempotencyClaim,
        *,
        request_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> None:
        try:
            completed = self.backend.complete_idempotency(
                claim.key,
                claim.fingerprint,
                request_id=request_id,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                ttl_seconds=self.result_ttl_seconds,
            )
        except IdempotencyBackendUnavailable as exc:
            self.observability.record_failure(IDEMPOTENCY, type(exc).__name__)
            raise IdempotencyUnavailableError() from exc
        if not completed:
            self.observability.record_failure(IDEMPOTENCY, "RecordStateMismatch")
            raise IdempotencyUnavailableError()
        self.observability.record_success(IDEMPOTENCY)

    def abandon(self, claim: IdempotencyClaim) -> None:
        try:
            self.backend.clear_idempotency(claim.key, claim.fingerprint)
        except IdempotencyBackendUnavailable as exc:
            self.observability.record_failure(IDEMPOTENCY, type(exc).__name__)
        else:
            self.observability.record_success(IDEMPOTENCY)


def get_idempotency_service(request: Request) -> IdempotencyService:
    return request.app.state.idempotency_service
