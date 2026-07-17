"""管理员授权回归：JWT 只识别用户，实时数据库角色决定权限。"""

from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.modules.auth.dependencies import require_admin
from app.modules.auth.maintenance import AdminRoleMaintenanceService
from app.modules.auth.models import User
from app.modules.auth.schemas import UserResponse
from app.modules.auth.tokens import TokenService, get_token_service

TEST_SECRET = "admin-tests-only-secret-longer-than-32-characters"


@pytest.fixture
def admin_client():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    token_service = TokenService(TEST_SECRET, expire_minutes=30)
    test_app = FastAPI()
    register_exception_handlers(test_app)

    def override_session():
        with Session(engine) as session:
            yield session

    @test_app.get("/admin-check")
    def admin_check(
        current_user: UserResponse = Depends(require_admin),
    ) -> dict[str, str]:
        return {"user_id": current_user.id}

    test_app.dependency_overrides[get_db_session] = override_session
    test_app.dependency_overrides[get_token_service] = lambda: token_service
    try:
        with TestClient(test_app) as client:
            yield client, engine, token_service
    finally:
        engine.dispose()


def create_user(engine, *, role: str = "user") -> User:
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        user = User(
            email="role-test@example.com",
            password_hash="not-used",
            is_active=True,
            role=role,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def test_normal_user_is_forbidden_and_admin_is_allowed(admin_client) -> None:
    client, engine, token_service = admin_client
    user = create_user(engine)
    headers = {
        "Authorization": f"Bearer {token_service.create_access_token(user.id)}"
    }

    forbidden = client.get("/admin-check", headers=headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ADMIN_REQUIRED"

    with Session(engine) as session:
        AdminRoleMaintenanceService(session).set_role(user.email, "admin")
    allowed = client.get("/admin-check", headers=headers)
    assert allowed.status_code == 200


def test_existing_token_loses_access_immediately_after_database_demotion(admin_client) -> None:
    client, engine, token_service = admin_client
    user = create_user(engine, role="admin")
    headers = {
        "Authorization": f"Bearer {token_service.create_access_token(user.id)}"
    }

    assert client.get("/admin-check", headers=headers).status_code == 200
    with Session(engine) as session:
        AdminRoleMaintenanceService(session).set_role(user.email, "user")
    assert client.get("/admin-check", headers=headers).status_code == 403
