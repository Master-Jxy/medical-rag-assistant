"""受控的账号角色维护用例，不向公开 HTTP API 暴露。"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.roles import UserRole

ALLOWED_MAINTENANCE_ROLES = {UserRole.USER, UserRole.ADMIN}


class UserNotFoundError(RuntimeError):
    pass


class InvalidRoleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SuperAdminInitializationResult:
    user: User
    operator: str
    changed: bool


class AdminRoleMaintenanceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def set_role(self, email: str, role: str) -> User:
        normalized_email = email.strip().lower()
        if role not in ALLOWED_MAINTENANCE_ROLES:
            raise InvalidRoleError(f"不支持的角色：{role}")

        user = self.repository.get_by_email(normalized_email)
        if user is None:
            raise UserNotFoundError(f"未找到账号：{normalized_email}")

        self.repository.set_role(user, role)
        self.session.commit()
        self.session.refresh(user)
        return user


class SuperAdminInitializationService:
    """只提升已存在账号；公开接口不得调用本维护用例。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def initialize(
        self,
        email: str,
        *,
        operator: str,
    ) -> SuperAdminInitializationResult:
        normalized_email = email.strip().lower()
        normalized_operator = operator.strip()
        if not normalized_operator:
            raise ValueError("操作者标识不能为空")

        user = self.repository.get_by_email(normalized_email)
        if user is None:
            raise UserNotFoundError(f"未找到账号：{normalized_email}")

        changed = user.role != UserRole.SUPER_ADMIN
        if changed:
            self.repository.set_role(user, UserRole.SUPER_ADMIN)
            self.session.commit()
            self.session.refresh(user)

        return SuperAdminInitializationResult(
            user=user,
            operator=normalized_operator,
            changed=changed,
        )
