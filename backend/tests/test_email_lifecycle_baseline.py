"""任务16.1a：邮箱字段、配置、Port和Fake基线。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.auth.fakes import FakeEmailSender, FakeEmailVerificationStore
from app.modules.auth.ports import (
    ChallengeConsumeResult,
    ChallengeCreateResult,
    EmailSenderPort,
    EmailVerificationStorePort,
    VerificationPurpose,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_email_configuration_has_safe_defaults_and_lazy_credentials() -> None:
    settings = Settings(_env_file=None)

    assert settings.smtp_host == "smtp.qq.com"
    assert settings.smtp_port == 465
    assert settings.smtp_use_ssl is True
    assert settings.email_code_ttl_seconds == 600
    assert settings.email_code_resend_seconds == 60
    assert settings.email_code_max_attempts == 5
    with pytest.raises(ValueError, match="SMTP_USERNAME"):
        settings.require_smtp_credentials()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("smtp_port", 0),
        ("smtp_timeout_seconds", 0),
        ("email_code_ttl_seconds", 59),
        ("email_code_resend_seconds", 0),
        ("email_code_max_attempts", 0),
    ],
)
def test_email_configuration_rejects_unsafe_ranges(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: value})


def test_smtp_secret_is_only_revealed_by_explicit_runtime_method() -> None:
    settings = Settings(
        _env_file=None,
        smtp_username=" sender@qq.com ",
        smtp_password="authorization-code",
    )

    assert settings.require_smtp_credentials() == (
        "sender@qq.com",
        "authorization-code",
    )
    assert "authorization-code" not in repr(settings)


def test_fake_adapters_satisfy_ports_and_atomically_consume() -> None:
    now = [100.0]
    store = FakeEmailVerificationStore(clock=lambda: now[0])
    sender = FakeEmailSender()
    sender_port: EmailSenderPort = sender
    store_port: EmailVerificationStorePort = store

    assert store_port.create_challenge(
        key="opaque-key",
        code_digest="digest",
        ttl_seconds=600,
        resend_seconds=60,
    ) is ChallengeCreateResult.CREATED
    assert store_port.create_challenge(
        key="opaque-key",
        code_digest="other",
        ttl_seconds=600,
        resend_seconds=60,
    ) is ChallengeCreateResult.COOLDOWN
    assert store_port.consume_challenge(
        key="opaque-key",
        code_digest="wrong",
        max_attempts=2,
    ) is ChallengeConsumeResult.INVALID
    assert store_port.consume_challenge(
        key="opaque-key",
        code_digest="digest",
        max_attempts=2,
    ) is ChallengeConsumeResult.CONSUMED
    assert store_port.consume_challenge(
        key="opaque-key",
        code_digest="digest",
        max_attempts=2,
    ) is ChallengeConsumeResult.EXPIRED

    sender_port.send_verification_code(
        recipient="user@example.com",
        purpose=VerificationPurpose.REGISTER,
        code="123456",
        ttl_seconds=600,
    )
    assert len(sender.sent) == 1


def test_fake_store_expires_and_invalidates_after_max_attempts() -> None:
    now = [100.0]
    store = FakeEmailVerificationStore(clock=lambda: now[0])
    store.create_challenge(
        key="attempt-key",
        code_digest="digest",
        ttl_seconds=60,
        resend_seconds=10,
    )
    assert store.consume_challenge(
        key="attempt-key", code_digest="wrong", max_attempts=1
    ) is ChallengeConsumeResult.ATTEMPTS_EXHAUSTED

    store.create_challenge(
        key="expiry-key",
        code_digest="digest",
        ttl_seconds=60,
        resend_seconds=10,
    )
    now[0] = 161.0
    assert store.consume_challenge(
        key="expiry-key", code_digest="digest", max_attempts=5
    ) is ChallengeConsumeResult.EXPIRED


def test_auth_ports_do_not_import_infrastructure_clients() -> None:
    source = (BACKEND_DIR / "app" / "modules" / "auth" / "ports.py").read_text(
        encoding="utf-8"
    )

    lowered = source.lower()
    assert "import redis" not in lowered
    assert "from redis" not in lowered
    assert "import smtplib" not in lowered
    assert "from smtplib" not in lowered
