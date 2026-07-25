"""管理员授权回归：JWT 只识别用户，实时数据库角色决定权限。"""

from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.modules.auth.dependencies import require_admin, require_super_admin
from app.modules.auth.maintenance import (
    AdminRoleMaintenanceService,
    InvalidRoleError,
    SuperAdminInitializationService,
)
from app.modules.auth.models import User
from app.modules.auth.roles import RolePolicy, UserRole
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

    @test_app.get("/super-admin-check")
    def super_admin_check(
        current_user: UserResponse = Depends(require_super_admin),
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


def test_super_admin_inherits_admin_access_but_admin_cannot_use_super_admin_route(
    admin_client,
) -> None:
    client, engine, token_service = admin_client
    user = create_user(engine, role="admin")
    headers = {
        "Authorization": f"Bearer {token_service.create_access_token(user.id)}"
    }

    assert client.get("/admin-check", headers=headers).status_code == 200
    forbidden = client.get("/super-admin-check", headers=headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ROLE_REQUIRED"

    with Session(engine) as session:
        result = SuperAdminInitializationService(session).initialize(
            user.email,
            operator="pytest",
        )
        assert result.changed is True

    assert client.get("/admin-check", headers=headers).status_code == 200
    assert client.get("/super-admin-check", headers=headers).status_code == 200


def test_super_admin_initialization_is_idempotent_and_generic_maintenance_cannot_grant_it(
    admin_client,
) -> None:
    _, engine, _ = admin_client
    user = create_user(engine)

    with Session(engine) as session:
        first = SuperAdminInitializationService(session).initialize(
            user.email,
            operator="first-run",
        )
        second = SuperAdminInitializationService(session).initialize(
            user.email,
            operator="second-run",
        )

        assert first.changed is True
        assert second.changed is False
        assert second.user.role == UserRole.SUPER_ADMIN
        with pytest.raises(InvalidRoleError):
            AdminRoleMaintenanceService(session).set_role(
                user.email,
                UserRole.SUPER_ADMIN,
            )


def test_inactive_super_admin_is_rejected_even_with_existing_token(admin_client) -> None:
    client, engine, token_service = admin_client
    user = create_user(engine, role="super_admin")
    headers = {
        "Authorization": f"Bearer {token_service.create_access_token(user.id)}"
    }
    assert client.get("/super-admin-check", headers=headers).status_code == 200

    with Session(engine) as session:
        saved = session.get(User, user.id)
        assert saved is not None
        saved.is_active = False
        session.commit()

    response = client.get("/super-admin-check", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_AUTH_TOKEN"


def test_role_policy_has_fixed_three_role_matrix() -> None:
    assert RolePolicy.ALL == {
        UserRole.USER,
        UserRole.ADMIN,
        UserRole.SUPER_ADMIN,
    }
    assert RolePolicy.is_admin(UserRole.USER) is False
    assert RolePolicy.is_admin(UserRole.ADMIN) is True
    assert RolePolicy.is_admin(UserRole.SUPER_ADMIN) is True
