"""任务16.1b：验证码注册、Redis与QQ SMTP无费用测试。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.infrastructure.qq_smtp_email_sender import QQSmtpEmailSender
from app.infrastructure.redis_email_verification_store import (
    RedisEmailVerificationStore,
)
from app.modules.auth.email_verification import (
    EmailVerificationService,
    EmailVerificationUnavailableError,
    InvalidEmailVerificationCodeError,
)
from app.modules.auth.fakes import FakeEmailSender, FakeEmailVerificationStore
from app.modules.auth.models import User
from app.modules.auth.ports import (
    ChallengeConsumeResult,
    ChallengeCreateResult,
    EmailVerificationBackendUnavailable,
    VerificationPurpose,
)
from app.modules.auth.schemas import UserCreate
from app.modules.auth.service import UserService

TEST_SECRET = "test-email-verification-secret-longer-than-32-characters"


class RecordingRedisClient:
    def __init__(self, results: list[object]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, int, tuple[object, ...]]] = []
        self.closed = False

    def eval(self, script: str, numkeys: int, *args: object) -> object:
        self.calls.append((script, numkeys, args))
        return next(self.results)

    def close(self) -> None:
        self.closed = True


class FailingRedisClient(RecordingRedisClient):
    def eval(self, script: str, numkeys: int, *args: object) -> object:
        raise ConnectionError("test-only failure")


class RecordingSmtpClient:
    def __init__(self) -> None:
        self.login_args: tuple[str, str] | None = None
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message) -> None:
        self.message = message


def build_settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret_key=TEST_SECRET,
        redis_url="redis://127.0.0.1:6379/15",
        **overrides,
    )


def test_redis_store_uses_atomic_lua_ttl_and_opaque_key() -> None:
    client = RecordingRedisClient([1, 2, 1])
    store = RedisEmailVerificationStore(
        build_settings(),
        client_factory=lambda *args, **kwargs: client,
    )
    opaque_key = "medical-rag:email-verification:register:abc123"

    assert store.create_challenge(
        key=opaque_key,
        code_digest="digest",
        ttl_seconds=600,
        resend_seconds=60,
    ) is ChallengeCreateResult.CREATED
    assert store.consume_challenge(
        key=opaque_key,
        code_digest="wrong",
        max_attempts=5,
    ) is ChallengeConsumeResult.INVALID
    store.delete_challenge(key=opaque_key)

    create_script, create_numkeys, create_args = client.calls[0]
    assert create_numkeys == 1
    assert "HSET" in create_script and "EXPIRE" in create_script
    assert create_args == (opaque_key, "digest", 600, 60)
    consume_script = client.calls[1][0]
    assert "HINCRBY" in consume_script and "DEL" in consume_script
    assert "@" not in repr(client.calls)


def test_redis_failure_is_stable_and_never_falls_back_to_memory() -> None:
    store = RedisEmailVerificationStore(
        build_settings(),
        client_factory=lambda *args, **kwargs: FailingRedisClient([]),
    )

    with pytest.raises(EmailVerificationBackendUnavailable):
        store.create_challenge(
            key="opaque",
            code_digest="digest",
            ttl_seconds=600,
            resend_seconds=60,
        )


def test_qq_smtp_adapter_uses_ssl_timeout_and_configured_credentials() -> None:
    client = RecordingSmtpClient()
    factory_calls: list[tuple[object, ...]] = []

    def factory(*args, **kwargs):
        factory_calls.append((*args, kwargs))
        return client

    sender = QQSmtpEmailSender(
        build_settings(
            smtp_username="sender@qq.com",
            smtp_password="test-authorization-code",
            smtp_timeout_seconds=7,
        ),
        smtp_ssl_factory=factory,
    )
    sender.send_verification_code(
        recipient="recipient@example.com",
        purpose=VerificationPurpose.REGISTER,
        code="123456",
        ttl_seconds=600,
    )

    assert factory_calls == [("smtp.qq.com", 465, {"timeout": 7.0})]
    assert client.login_args == ("sender@qq.com", "test-authorization-code")
    assert client.message["To"] == "recipient@example.com"
    assert "123456" in client.message.get_content()


def test_register_requires_code_consumes_once_and_marks_email_verified() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = FakeEmailVerificationStore()
    sender = FakeEmailSender()
    verification = EmailVerificationService(
        store=store,
        sender=sender,
        settings=build_settings(),
        secret_key=TEST_SECRET,
        code_generator=lambda: "123456",
    )

    with Session(engine) as session:
        service = UserService(session, verification)
        service.request_registration_code("student@example.com")
        request = UserCreate(
            email="student@example.com",
            password="safe-password",
            verification_code="123456",
        )
        created = service.register(request)
        saved = session.get(User, created.id)
        assert saved is not None
        assert saved.email_verified_at is not None

        with pytest.raises(InvalidEmailVerificationCodeError):
            UserService(session, verification).register(
                UserCreate(
                    email="another@example.com",
                    password="safe-password",
                    verification_code="123456",
                )
            )
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_atomic_consume_allows_only_one_concurrent_winner() -> None:
    store = FakeEmailVerificationStore()
    store.create_challenge(
        key="opaque",
        code_digest="digest",
        ttl_seconds=600,
        resend_seconds=60,
    )

    def consume() -> ChallengeConsumeResult:
        return store.consume_challenge(
            key="opaque", code_digest="digest", max_attempts=5
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))

    assert results.count(ChallengeConsumeResult.CONSUMED) == 1
    assert results.count(ChallengeConsumeResult.EXPIRED) == 1


def test_smtp_failure_removes_challenge_and_redis_failure_is_publicly_safe() -> None:
    store = FakeEmailVerificationStore()
    verification = EmailVerificationService(
        store=store,
        sender=FakeEmailSender(failure=RuntimeError("smtp secret detail")),
        settings=build_settings(),
        secret_key=TEST_SECRET,
        code_generator=lambda: "123456",
    )

    with pytest.raises(EmailVerificationUnavailableError) as caught:
        verification.request_code(
            email="student@example.com",
            purpose=VerificationPurpose.REGISTER,
        )
    assert "smtp secret detail" not in caught.value.message

    assert store.create_challenge(
        key=verification._key("student@example.com", VerificationPurpose.REGISTER),
        code_digest="new-digest",
        ttl_seconds=600,
        resend_seconds=60,
    ) is ChallengeCreateResult.CREATED
