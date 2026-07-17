"""受控的账号角色维护用例，不向公开 HTTP API 暴露。"""

from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository

ALLOWED_ROLES = {"user", "admin"}


class UserNotFoundError(RuntimeError):
    pass


class InvalidRoleError(ValueError):
    pass


class AdminRoleMaintenanceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def set_role(self, email: str, role: str) -> User:
        normalized_email = email.strip().lower()
        if role not in ALLOWED_ROLES:
            raise InvalidRoleError(f"不支持的角色：{role}")

        user = self.repository.get_by_email(normalized_email)
        if user is None:
            raise UserNotFoundError(f"未找到账号：{normalized_email}")

        self.repository.set_role(user, role)
        self.session.commit()
        self.session.refresh(user)
        return user
