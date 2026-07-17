"""认证限流用例：选择策略并在 Redis 失效时切换到有界本机保护。"""

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.rate_limit_service import RateLimitService


class AuthRateLimitExceededError(AppError):
    def __init__(self, retry_after_seconds: int) -> None:
        retry_after = max(1, retry_after_seconds)
        super().__init__(
            "操作过于频繁，请稍后再试",
            code="AUTH_RATE_LIMITED",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )


class AuthRateLimitService:
    """注册和登录共享安全响应，但使用各自独立的窗口与额度。"""

    def __init__(
        self,
        rate_limiter: RateLimitService,
        settings: Settings,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.settings = settings

    def check_register(self, client_address: str) -> None:
        self._check(
            "register",
            client_address,
            self.settings.auth_register_rate_limit,
            self.settings.auth_register_rate_window_seconds,
        )

    def check_login(self, client_address: str) -> None:
        self._check(
            "login",
            client_address,
            self.settings.auth_login_rate_limit,
            self.settings.auth_login_rate_window_seconds,
        )

    def _check(
        self,
        action: str,
        client_address: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        decision = self.rate_limiter.consume(
            f"auth:{action}", client_address, limit, window_seconds
        )

        if not decision.allowed:
            raise AuthRateLimitExceededError(decision.retry_after_seconds)
