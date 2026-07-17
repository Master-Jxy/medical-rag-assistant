"""共享限流编排：生成脱敏业务键，并在主计数器故障时安全降级。"""

import hashlib

from app.ports.rate_limit import (
    RateLimitBackendUnavailable,
    RateLimitDecision,
    RateLimitPort,
)
from app.services.protection_observability import (
    ProtectionObservability,
    RATE_LIMIT,
)


class RateLimitService:
    def __init__(
        self,
        primary: RateLimitPort,
        fallback: RateLimitPort,
        observability: ProtectionObservability | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.observability = observability or ProtectionObservability(
            redis_configured=True
        )

    def consume(
        self,
        namespace: str,
        subject: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
        key = f"medical-rag:{namespace}:{digest}"
        try:
            decision = self.primary.consume(key, limit, window_seconds)
            self.observability.record_success(RATE_LIMIT)
            return decision
        except RateLimitBackendUnavailable as exc:
            self.observability.record_failure(RATE_LIMIT, type(exc).__name__)
            return self.fallback.consume(key, limit, window_seconds)
