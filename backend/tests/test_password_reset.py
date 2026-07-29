"""任务16.1c：忘记密码、JWT版本与统一公开响应。"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.dependencies import (
    get_auth_rate_limit_service,
    get_email_verification_service,
)
from app.modules.auth.email_verification import EmailVerificationService
from app.modules.auth.fakes import FakeEmailSender, FakeEmailVerificationStore
from app.modules.auth.models import User
from app.modules.auth.ports import VerificationPurpose
from app.modules.auth.tokens import TokenService, get_token_service

TEST_SECRET = "test-password-reset-secret-that-is-longer-than-32-characters"
EMAIL = "reset@example.com"
PASSWORD = "before-reset-password"
NEW_PASSWORD = "after-reset-password"


class AllowAllRateLimiter:
    def check_register(self, client_address: str) -> None:
        pass

    def check_login(self, client_address: str) -> None:
        pass

    def check_email_verification(
        self, *, action: str, client_address: str, email: str
    ) -> None:
        pass


@pytest.fixture
def reset_client():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sender = FakeEmailSender()
    store = FakeEmailVerificationStore()
    settings = Settings(_env_file=None, jwt_secret_key=TEST_SECRET)
    verification = EmailVerificationService(
        store=store,
        sender=sender,
        settings=settings,
        secret_key=TEST_SECRET,
        code_generator=lambda: "654321",
    )
    token_service = TokenService(TEST_SECRET)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_email_verification_service] = lambda: verification
    app.dependency_overrides[get_auth_rate_limit_service] = AllowAllRateLimiter
    app.dependency_overrides[get_token_service] = lambda: token_service
    try:
        with TestClient(app) as client:
            verification.request_code(
                email=EMAIL,
                purpose=VerificationPurpose.REGISTER,
            )
            registered = client.post(
                "/api/v1/auth/register",
                json={
                    "email": EMAIL,
                    "password": PASSWORD,
                    "verification_code": "654321",
                },
            )
            assert registered.status_code == 201
            yield client, engine, sender
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def login(client: TestClient, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": password},
    )


def test_password_reset_invalidates_old_jwt_and_changes_password(reset_client) -> None:
    client, engine, _ = reset_client
    before = login(client, PASSWORD)
    assert before.status_code == 200
    old_token = before.json()["access_token"]

    requested = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": EMAIL},
    )
    confirmed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": EMAIL,
            "verification_code": "654321",
            "new_password": NEW_PASSWORD,
        },
    )

    assert requested.status_code == 202
    assert confirmed.status_code == 200
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {old_token}"},
    ).status_code == 401
    assert login(client, PASSWORD).status_code == 401
    new_login = login(client, NEW_PASSWORD)
    assert new_login.status_code == 200
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_login.json()['access_token']}"},
    ).status_code == 200
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        assert user.token_version == 1


def test_password_reset_verifies_legacy_unverified_email(reset_client) -> None:
    client, engine, _ = reset_client
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        user.email_verified_at = None
        session.commit()

    requested = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": EMAIL},
    )
    confirmed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": EMAIL,
            "verification_code": "654321",
            "new_password": NEW_PASSWORD,
        },
    )

    assert requested.status_code == 202
    assert confirmed.status_code == 200
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        assert user.email_verified_at is not None
        assert user.token_version == 1


def test_password_reset_request_is_identical_for_missing_and_inactive(reset_client) -> None:
    client, engine, sender = reset_client
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        user.is_active = False
        session.commit()
    sent_before = len(sender.sent)

    inactive = client.post(
        "/api/v1/auth/password-reset/request", json={"email": EMAIL}
    )
    missing = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )

    assert inactive.status_code == missing.status_code == 202
    assert inactive.json() == missing.json()
    assert len(sender.sent) == sent_before


def test_invalid_and_replayed_reset_code_never_changes_password(reset_client) -> None:
    client, engine, _ = reset_client
    client.post("/api/v1/auth/password-reset/request", json={"email": EMAIL})

    invalid = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": EMAIL,
            "verification_code": "000000",
            "new_password": NEW_PASSWORD,
        },
    )
    valid = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": EMAIL,
            "verification_code": "654321",
            "new_password": NEW_PASSWORD,
        },
    )
    replay = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "email": EMAIL,
            "verification_code": "654321",
            "new_password": "another-new-password",
        },
    )

    assert invalid.status_code == 400
    assert valid.status_code == 200
    assert replay.status_code == 400
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        assert user.token_version == 1


def test_concurrent_reset_confirmation_has_one_winner(reset_client) -> None:
    client, engine, _ = reset_client
    client.post("/api/v1/auth/password-reset/request", json={"email": EMAIL})

    def confirm(index: int) -> int:
        with TestClient(app) as thread_client:
            return thread_client.post(
                "/api/v1/auth/password-reset/confirm",
                json={
                    "email": EMAIL,
                    "verification_code": "654321",
                    "new_password": f"concurrent-password-{index}",
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(confirm, range(2)))

    assert sorted(statuses) == [200, 400]
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user is not None
        assert user.token_version == 1
