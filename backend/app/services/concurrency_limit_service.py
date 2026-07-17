"""共享并发保护编排：生成脱敏键并记录占位实际所在的后端。"""

import hashlib
from dataclasses import dataclass
from uuid import uuid4

from app.ports.concurrency_limit import (
    ConcurrencyLimitBackendUnavailable,
    ConcurrencyLimitPort,
)
from app.services.protection_observability import (
    ProtectionObservability,
    UPLOAD_CONCURRENCY,
)

@dataclass(frozen=True)
class ConcurrencyLease:
    key: str
    owner_token: str
    backend: ConcurrencyLimitPort
    retry_after_seconds: int


@dataclass(frozen=True)
class ConcurrencyAcquireResult:
    lease: ConcurrencyLease | None
    retry_after_seconds: int


class ConcurrencyLimitService:
    def __init__(
        self,
        primary: ConcurrencyLimitPort,
        fallback: ConcurrencyLimitPort,
        observability: ProtectionObservability | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.observability = observability or ProtectionObservability(
            redis_configured=True
        )

    def acquire(
        self,
        namespace: str,
        subject: str,
        limit: int,
        ttl_seconds: int,
    ) -> ConcurrencyAcquireResult:
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
        key = f"medical-rag:{namespace}:{digest}"
        owner_token = uuid4().hex
        backend = self.primary
        try:
            decision = backend.acquire(key, owner_token, limit, ttl_seconds)
            self.observability.record_success(UPLOAD_CONCURRENCY)
        except ConcurrencyLimitBackendUnavailable as exc:
            self.observability.record_failure(
                UPLOAD_CONCURRENCY, type(exc).__name__
            )
            backend = self.fallback
            decision = backend.acquire(key, owner_token, limit, ttl_seconds)

        if not decision.acquired:
            return ConcurrencyAcquireResult(None, decision.retry_after_seconds)
        return ConcurrencyAcquireResult(
            ConcurrencyLease(
                key,
                owner_token,
                backend,
                decision.retry_after_seconds,
            ),
            decision.retry_after_seconds,
        )

    def release(self, lease: ConcurrencyLease) -> None:
        try:
            lease.backend.release(lease.key, lease.owner_token)
        except ConcurrencyLimitBackendUnavailable as exc:
            self.observability.record_failure(
                UPLOAD_CONCURRENCY, type(exc).__name__
            )
