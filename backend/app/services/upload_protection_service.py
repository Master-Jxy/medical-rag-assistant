"""普通用户上传保护：频率额度与并发占位均在昂贵处理前完成。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.concurrency_limit_service import ConcurrencyLimitService
from app.services.rate_limit_service import RateLimitService

T = TypeVar("T")


@dataclass(frozen=True)
class UploadProtectionPolicy:
    enforce_rate_limit: bool = True


STANDARD_UPLOAD_POLICY = UploadProtectionPolicy()
ADMIN_UPLOAD_POLICY = UploadProtectionPolicy(enforce_rate_limit=False)


class UploadRateLimitExceededError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        retry_after = max(1, retry_after_seconds)
        super().__init__(
            "上传请求过于频繁，请稍后再试",
            code="UPLOAD_RATE_LIMITED",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )


class UploadConcurrencyExceededError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        retry_after = max(1, retry_after_seconds)
        super().__init__(
            "已有文档正在处理中，请稍后再试",
            code="UPLOAD_CONCURRENCY_LIMITED",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )


class UploadProtectionService:
    def __init__(
        self,
        rate_limiter: RateLimitService,
        concurrency_limiter: ConcurrencyLimitService,
        settings: Settings,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.concurrency_limiter = concurrency_limiter
        self.settings = settings

    async def execute(
        self,
        user_id: str,
        operation: Callable[[], Awaitable[T]],
        *,
        policy: UploadProtectionPolicy = STANDARD_UPLOAD_POLICY,
    ) -> T:
        if policy.enforce_rate_limit:
            rate_decision = self.rate_limiter.consume(
                "upload:frequency",
                user_id,
                self.settings.upload_rate_limit,
                self.settings.upload_rate_window_seconds,
            )
            if not rate_decision.allowed:
                raise UploadRateLimitExceededError(rate_decision.retry_after_seconds)

        concurrency = self.concurrency_limiter.acquire(
            "upload:concurrency",
            user_id,
            self.settings.upload_concurrency_limit,
            self.settings.upload_concurrency_ttl_seconds,
        )
        if concurrency.lease is None:
            raise UploadConcurrencyExceededError(concurrency.retry_after_seconds)

        try:
            return await operation()
        finally:
            self.concurrency_limiter.release(concurrency.lease)


def get_upload_protection_service(request: Request) -> UploadProtectionService:
    return request.app.state.upload_protection_service
