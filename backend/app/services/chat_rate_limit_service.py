"""聊天限流策略：所有问答入口共享同一份按用户额度。"""

from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.rate_limit_service import RateLimitService


class ChatRateLimitExceededError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        retry_after = max(1, retry_after_seconds)
        super().__init__(
            "问答请求过于频繁，请稍后再试",
            code="CHAT_RATE_LIMITED",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )


class ChatRateLimitService:
    def __init__(self, rate_limiter: RateLimitService, settings: Settings) -> None:
        self.rate_limiter = rate_limiter
        self.settings = settings

    def check(self, user_id: str) -> None:
        decision = self.rate_limiter.consume(
            "chat:user",
            user_id,
            self.settings.chat_rate_limit,
            self.settings.chat_rate_window_seconds,
        )
        if not decision.allowed:
            raise ChatRateLimitExceededError(decision.retry_after_seconds)


def get_chat_rate_limit_service(request: Request) -> ChatRateLimitService:
    return request.app.state.chat_rate_limit_service
