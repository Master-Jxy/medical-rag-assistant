"""超级管理员用户治理用例。"""

from app.core.exceptions import AppError
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.auth.repository import UserRepository
from app.modules.auth.roles import UserRole
from app.modules.auth.schemas import UserListResponse, UserResponse
from sqlalchemy.orm import Session


class ManagedUserNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("未找到指定用户", code="USER_NOT_FOUND", status_code=404)


class SuperAdminRoleProtectedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "不能通过该接口修改超级管理员角色",
            code="SUPER_ADMIN_ROLE_PROTECTED",
            status_code=409,
        )


class LastSuperAdminError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "系统必须保留至少一个有效超级管理员",
            code="LAST_SUPER_ADMIN_REQUIRED",
            status_code=409,
        )


class UserAdministrationService:
    def __init__(
        self,
        session: Session,
        audit: AuditPort,
    ) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.audit = audit

    def list_users(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> UserListResponse:
        normalized_search = search.strip() if search else None
        role_value = role.value if role else None
        users = self.repository.list_users(
            offset=offset,
            limit=limit,
            search=normalized_search,
            role=role_value,
            is_active=is_active,
        )
        total = self.repository.count_users(
            search=normalized_search,
            role=role_value,
            is_active=is_active,
        )
        return UserListResponse(
            items=[UserResponse.model_validate(user) for user in users],
            total=total,
            offset=offset,
            limit=limit,
        )

    def update_role(
        self,
        user_id: str,
        role: UserRole,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> UserResponse:
        user = self.repository.get_by_id(user_id)
        if user is None:
            raise ManagedUserNotFoundError()
        if user.role == UserRole.SUPER_ADMIN:
            raise SuperAdminRoleProtectedError()
        if role is UserRole.SUPER_ADMIN:
            raise SuperAdminRoleProtectedError()
        if user.role == role:
            return UserResponse.model_validate(user)

        previous_role = user.role
        self.repository.set_role(user, role)
        self.audit.record(
            AuditRecord(
                actor_user_id=actor_user_id,
                action="user.role_changed",
                object_type="user",
                object_id=user.id,
                request_id=request_id,
                details={"from_role": previous_role, "to_role": role.value},
            )
        )
        self.session.commit()
        self.session.refresh(user)
        return UserResponse.model_validate(user)

    def update_status(
        self,
        user_id: str,
        is_active: bool,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> UserResponse:
        user = self.repository.get_by_id(user_id)
        if user is None:
            raise ManagedUserNotFoundError()
        if user.is_active is is_active:
            return UserResponse.model_validate(user)

        if user.role == UserRole.SUPER_ADMIN and not is_active:
            active_super_admins = self.repository.lock_active_super_admins()
            if len(active_super_admins) <= 1:
                raise LastSuperAdminError()

        previous_status = user.is_active
        self.repository.set_active(user, is_active)
        self.audit.record(
            AuditRecord(
                actor_user_id=actor_user_id,
                action="user.status_changed",
                object_type="user",
                object_id=user.id,
                request_id=request_id,
                details={"from_active": previous_status, "to_active": is_active},
            )
        )
        self.session.commit()
        self.session.refresh(user)
        return UserResponse.model_validate(user)
