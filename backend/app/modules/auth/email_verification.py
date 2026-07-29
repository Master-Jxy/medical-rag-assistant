"""邮箱验证码用例：生成、脱敏存储、发送、原子校验与补偿。"""

import hashlib
import hmac
import secrets
from typing import Callable

from app.core.config import Settings
from app.core.exceptions import AppError
from app.modules.auth.ports import (
    ChallengeConsumeResult,
    ChallengeCreateResult,
    EmailSenderPort,
    EmailVerificationBackendUnavailable,
    EmailVerificationStorePort,
    VerificationPurpose,
)


class EmailVerificationRateLimitedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "操作过于频繁，请稍后再试",
            code="EMAIL_VERIFICATION_RATE_LIMITED",
            status_code=429,
        )


class EmailVerificationUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "验证码服务暂时不可用，请稍后重试",
            code="EMAIL_VERIFICATION_UNAVAILABLE",
            status_code=503,
        )


class InvalidEmailVerificationCodeError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "验证码无效或已过期",
            code="INVALID_EMAIL_VERIFICATION_CODE",
            status_code=400,
        )


class EmailVerificationService:
    def __init__(
        self,
        *,
        store: EmailVerificationStorePort,
        sender: EmailSenderPort,
        settings: Settings,
        secret_key: str,
        code_generator: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.sender = sender
        self.settings = settings
        self._secret = secret_key.encode("utf-8")
        self._code_generator = code_generator or self._generate_code

    def request_code(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
        should_send: bool = True,
    ) -> None:
        """不存在账号等枚举场景可跳过发送，但公开响应必须由Router保持一致。"""
        if not should_send:
            self._key(email, purpose)
            return
        code = self._code_generator()
        key = self._key(email, purpose)
        digest = self._code_digest(key, code)
        try:
            result = self.store.create_challenge(
                key=key,
                code_digest=digest,
                ttl_seconds=self.settings.email_code_ttl_seconds,
                resend_seconds=self.settings.email_code_resend_seconds,
            )
        except EmailVerificationBackendUnavailable as exc:
            raise EmailVerificationUnavailableError() from exc
        if result is ChallengeCreateResult.COOLDOWN:
            raise EmailVerificationRateLimitedError()

        try:
            self.sender.send_verification_code(
                recipient=email,
                purpose=purpose,
                code=code,
                ttl_seconds=self.settings.email_code_ttl_seconds,
            )
        except Exception as exc:
            try:
                self.store.delete_challenge(key=key)
            except EmailVerificationBackendUnavailable:
                pass
            raise EmailVerificationUnavailableError() from exc

    def consume_code(
        self,
        *,
        email: str,
        purpose: VerificationPurpose,
        code: str,
    ) -> None:
        key = self._key(email, purpose)
        try:
            result = self.store.consume_challenge(
                key=key,
                code_digest=self._code_digest(key, code),
                max_attempts=self.settings.email_code_max_attempts,
            )
        except EmailVerificationBackendUnavailable as exc:
            raise EmailVerificationUnavailableError() from exc
        if result is not ChallengeConsumeResult.CONSUMED:
            raise InvalidEmailVerificationCodeError()

    def _key(self, email: str, purpose: VerificationPurpose) -> str:
        normalized = email.strip().lower()
        subject = f"{purpose.value}:{normalized}".encode("utf-8")
        digest = hmac.new(self._secret, subject, hashlib.sha256).hexdigest()
        return f"medical-rag:email-verification:{purpose.value}:{digest}"

    def _code_digest(self, key: str, code: str) -> str:
        value = f"{key}:{code}".encode("utf-8")
        return hmac.new(self._secret, value, hashlib.sha256).hexdigest()

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"
