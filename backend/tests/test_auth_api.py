"""认证接口回归：使用 SQLite 和测试密钥，不访问真实 MySQL 或外部模型。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.auth.models import User
from app.modules.auth.dependencies import get_auth_rate_limit_service
from app.modules.auth.rate_limit import AuthRateLimitExceededError
from app.modules.auth.passwords import verify_password
from app.modules.auth.tokens import TokenService, get_token_service

TEST_SECRET = "test-only-jwt-secret-that-is-longer-than-32-characters"
REGISTER_BODY = {
    "email": "Student@Example.com",
    "password": "SafePassword_2026!",
    "display_name": "医学资料学习者",
}


class AllowAllRateLimiter:
    def check_register(self, client_address: str) -> None:
        pass

    def check_login(self, client_address: str) -> None:
        pass


class RejectAllRateLimiter:
    def check_register(self, client_address: str) -> None:
        raise AuthRateLimitExceededError(23)

    def check_login(self, client_address: str) -> None:
        raise AuthRateLimitExceededError(23)


@pytest.fixture
def auth_client():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    token_service = TokenService(TEST_SECRET, expire_minutes=30)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_auth_rate_limit_service] = AllowAllRateLimiter
    try:
        with TestClient(app) as client:
            yield client, engine, token_service
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def register_user(client: TestClient) -> dict:
    response = client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert response.status_code == 201
    return response.json()


def test_register_returns_safe_user_and_stores_only_password_hash(auth_client) -> None:
    client, engine, _ = auth_client
    body = register_user(client)

    assert body["email"] == "student@example.com"
    assert body["display_name"] == "医学资料学习者"
    assert body["role"] == "user"
    assert "password" not in body
    assert "password_hash" not in body

    with Session(engine) as session:
        saved = session.scalar(select(User).where(User.id == body["id"]))
        assert saved is not None
        assert saved.password_hash != REGISTER_BODY["password"]
        assert verify_password(REGISTER_BODY["password"], saved.password_hash)
        assert saved.role == "user"


def test_register_rejects_duplicate_email(auth_client) -> None:
    client, _, _ = auth_client
    register_user(client)

    duplicate = {**REGISTER_BODY, "email": "STUDENT@example.COM"}
    response = client.post("/api/v1/auth/register", json=duplicate)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "EMAIL_ALREADY_REGISTERED",
        "message": "该邮箱已注册",
    }


def test_login_returns_bearer_token_and_me_returns_current_user(auth_client) -> None:
    client, _, _ = auth_client
    registered = register_user(client)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "STUDENT@EXAMPLE.COM", "password": REGISTER_BODY["password"]},
    )
    assert login.status_code == 200
    token_body = login.json()
    assert token_body["token_type"] == "bearer"
    assert token_body["expires_in"] == 1800
    assert token_body["access_token"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json() == registered


def test_unknown_email_and_wrong_password_share_the_same_safe_error(auth_client) -> None:
    client, _, _ = auth_client
    register_user(client)

    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "wrong-password"},
        ),
        client.post(
            "/api/v1/auth/login",
            json={"email": REGISTER_BODY["email"], "password": "wrong-password"},
        ),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"] == {
            "code": "INVALID_CREDENTIALS",
            "message": "邮箱或密码错误",
        }


def test_missing_forged_and_expired_tokens_all_return_401(auth_client) -> None:
    client, _, token_service = auth_client
    user = register_user(client)
    expired = token_service.create_access_token(
        user["id"], expires_delta=timedelta(seconds=-1)
    )

    responses = [
        client.get("/api/v1/auth/me"),
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer forged-token"}),
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"] == {
            "code": "INVALID_AUTH_TOKEN",
            "message": "登录凭证无效或已过期",
        }


def test_valid_token_for_missing_user_is_rejected(auth_client) -> None:
    client, _, token_service = auth_client
    token = token_service.create_access_token("deleted-user-id")

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_AUTH_TOKEN"


def test_register_and_login_share_stable_rate_limit_response(auth_client) -> None:
    client, engine, _ = auth_client
    app.dependency_overrides[get_auth_rate_limit_service] = RejectAllRateLimiter

    responses = [
        client.post("/api/v1/auth/register", json=REGISTER_BODY),
        client.post(
            "/api/v1/auth/login",
            json={"email": REGISTER_BODY["email"], "password": "wrong-password"},
        ),
    ]

    for response in responses:
        assert response.status_code == 429
        assert response.headers["retry-after"] == "23"
        assert response.json()["error"] == {
            "code": "AUTH_RATE_LIMITED",
            "message": "操作过于频繁，请稍后再试",
        }
        assert response.json()["request_id"]

    with Session(engine) as session:
        assert session.scalar(select(User)) is None
