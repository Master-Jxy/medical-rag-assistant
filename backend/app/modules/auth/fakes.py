"""邮箱生命周期的无外部副作用Fake适配器。"""

from dataclasses import dataclass
from threading import Lock
import time

from app.modules.auth.ports import (
    ChallengeConsumeResult,
    ChallengeCreateResult,
    VerificationPurpose,
)


@dataclass(frozen=True)
class SentVerificationEmail:
    recipient: str
    purpose: VerificationPurpose
    code: str
    ttl_seconds: int


class FakeEmailSender:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.sent: list[SentVerificationEmail] = []

    def send_verification_code(
        self,
        *,
        recipient: str,
        purpose: VerificationPurpose,
        code: str,
        ttl_seconds: int,
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.sent.append(
            SentVerificationEmail(
                recipient=recipient,
                purpose=purpose,
                code=code,
                ttl_seconds=ttl_seconds,
            )
        )


@dataclass
class _FakeChallenge:
    code_digest: str
    expires_at: float
    resend_at: float
    failed_attempts: int = 0


class FakeEmailVerificationStore:
    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, _FakeChallenge] = {}
        self._lock = Lock()

    def create_challenge(
        self,
        *,
        key: str,
        code_digest: str,
        ttl_seconds: int,
        resend_seconds: int,
    ) -> ChallengeCreateResult:
        with self._lock:
            now = self._clock()
            current = self._items.get(key)
            if current is not None and now < current.resend_at:
                return ChallengeCreateResult.COOLDOWN
            self._items[key] = _FakeChallenge(
                code_digest=code_digest,
                expires_at=now + ttl_seconds,
                resend_at=now + resend_seconds,
            )
            return ChallengeCreateResult.CREATED

    def consume_challenge(
        self,
        *,
        key: str,
        code_digest: str,
        max_attempts: int,
    ) -> ChallengeConsumeResult:
        with self._lock:
            current = self._items.get(key)
            if current is None:
                return ChallengeConsumeResult.EXPIRED
            if self._clock() >= current.expires_at:
                self._items.pop(key, None)
                return ChallengeConsumeResult.EXPIRED
            if current.code_digest == code_digest:
                self._items.pop(key, None)
                return ChallengeConsumeResult.CONSUMED
            current.failed_attempts += 1
            if current.failed_attempts >= max_attempts:
                self._items.pop(key, None)
                return ChallengeConsumeResult.ATTEMPTS_EXHAUSTED
            return ChallengeConsumeResult.INVALID

    def delete_challenge(self, *, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)
