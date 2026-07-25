"""超级管理员用户治理接口的权限、状态与审计回归。"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.auth.tokens import get_token_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def build_client(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'user-admin.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    return engine, factory


def test_only_super_admin_can_list_and_manage_users_with_audit(tmp_path) -> None:
    engine, factory = build_client(tmp_path)
    normal = create_test_user(factory, "managed-normal")
    admin = create_test_user(factory, "managed-admin", role="admin")
    owner = create_test_user(factory, "managed-owner", role="super_admin")
    try:
        with TestClient(app) as client:
            assert client.get(
                "/api/v1/super-admin/users",
                headers=auth_headers(normal.id),
            ).status_code == 403
            assert client.get(
                "/api/v1/super-admin/users",
                headers=auth_headers(admin.id),
            ).status_code == 403

            listed = client.get(
                "/api/v1/super-admin/users?role=user&limit=10",
                headers=auth_headers(owner.id),
            )
            assert listed.status_code == 200
            assert listed.json()["total"] == 1
            assert listed.json()["items"][0]["id"] == normal.id

            promoted = client.patch(
                f"/api/v1/super-admin/users/{normal.id}/role",
                json={"role": "admin"},
                headers=auth_headers(owner.id),
            )
            assert promoted.status_code == 200
            assert promoted.json()["role"] == "admin"

            # 原JWT只保存用户ID，数据库角色变化立即生效。
            assert client.get(
                "/api/v1/admin/telemetry/stats",
                headers=auth_headers(normal.id),
            ).status_code == 200

            repeated = client.patch(
                f"/api/v1/super-admin/users/{normal.id}/role",
                json={"role": "admin"},
                headers=auth_headers(owner.id),
            )
            assert repeated.status_code == 200

        with factory() as session:
            events = session.scalars(select(AuditEvent)).all()
            assert len(events) == 1
            assert events[0].action == "user.role_changed"
            assert events[0].actor_user_id == owner.id
            assert events[0].object_id == normal.id
            assert events[0].details == {
                "from_role": "user",
                "to_role": "admin",
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_account_status_is_immediate_and_last_super_admin_is_protected(
    tmp_path,
) -> None:
    engine, factory = build_client(tmp_path)
    owner = create_test_user(factory, "status-owner", role="super_admin")
    target = create_test_user(factory, "status-target")
    try:
        with TestClient(app) as client:
            blocked = client.patch(
                f"/api/v1/super-admin/users/{owner.id}/status",
                json={"is_active": False},
                headers=auth_headers(owner.id),
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "LAST_SUPER_ADMIN_REQUIRED"

            disabled = client.patch(
                f"/api/v1/super-admin/users/{target.id}/status",
                json={"is_active": False},
                headers=auth_headers(owner.id),
            )
            assert disabled.status_code == 200
            assert disabled.json()["is_active"] is False

            rejected = client.get(
                "/api/v1/auth/me",
                headers=auth_headers(target.id),
            )
            assert rejected.status_code == 401

        with factory() as session:
            assert session.scalar(
                select(func.count()).select_from(AuditEvent)
            ) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_http_cannot_grant_or_demote_super_admin(tmp_path) -> None:
    engine, factory = build_client(tmp_path)
    owner = create_test_user(factory, "protected-owner", role="super_admin")
    target = create_test_user(factory, "protected-target")
    try:
        with TestClient(app) as client:
            invalid_grant = client.patch(
                f"/api/v1/super-admin/users/{target.id}/role",
                json={"role": "super_admin"},
                headers=auth_headers(owner.id),
            )
            assert invalid_grant.status_code == 422

            protected = client.patch(
                f"/api/v1/super-admin/users/{owner.id}/role",
                json={"role": "admin"},
                headers=auth_headers(owner.id),
            )
            assert protected.status_code == 409
            assert protected.json()["error"]["code"] == "SUPER_ADMIN_ROLE_PROTECTED"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
