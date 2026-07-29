"""邮箱认证外部能力的稳定Port；不暴露Redis或SMTP客户端。"""

from typing import Protocol

from app.core.enums import StrEnum


class VerificationPurpose(StrEnum):
    REGISTER = "register"
    PASSWORD_RESET = "password_reset"


class ChallengeCreateResult(StrEnum):
    CREATED = "created"
    COOLDOWN = "cooldown"


class ChallengeConsumeResult(StrEnum):
    CONSUMED = "consumed"
    INVALID = "invalid"
    EXPIRED = "expired"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


class EmailVerificationBackendUnavailable(RuntimeError):
    """验证码存储不可用；调用方必须安全失败，不能降级到本机内存。"""


class EmailSenderPort(Protocol):
    def send_verification_code(
        self,
        *,
        recipient: str,
        purpose: VerificationPurpose,
        code: str,
        ttl_seconds: int,
    ) -> None:
        """发送一次验证码；实现不得记录收件人、验证码或授权码。"""


class EmailVerificationStorePort(Protocol):
    def create_challenge(
        self,
        *,
        key: str,
        code_digest: str,
        ttl_seconds: int,
        resend_seconds: int,
    ) -> ChallengeCreateResult:
        """原子创建挑战；冷却期内不得覆盖已有验证码。"""

    def consume_challenge(
        self,
        *,
        key: str,
        code_digest: str,
        max_attempts: int,
    ) -> ChallengeConsumeResult:
        """原子校验并消费；失败次数达到上限时作废。"""

    def delete_challenge(self, *, key: str) -> None:
        """邮件发送失败时删除刚创建的挑战，允许安全重试。"""
