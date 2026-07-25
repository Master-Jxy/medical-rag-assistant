"""认证模块的固定角色集合与集中授权策略。"""

from typing import Iterable

from app.core.enums import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class RolePolicy:
    """只判断角色能力，不读取请求、数据库或前端状态。"""

    ALL = frozenset(UserRole)
    ADMINISTRATORS = frozenset({UserRole.ADMIN, UserRole.SUPER_ADMIN})

    @classmethod
    def normalize(cls, role: UserRole | str) -> UserRole:
        return role if isinstance(role, UserRole) else UserRole(role)

    @classmethod
    def allows(
        cls,
        actual_role: UserRole | str,
        allowed_roles: Iterable[UserRole | str],
    ) -> bool:
        actual = cls.normalize(actual_role)
        allowed = frozenset(cls.normalize(role) for role in allowed_roles)
        return actual in allowed

    @classmethod
    def is_admin(cls, role: UserRole | str) -> bool:
        return cls.allows(role, cls.ADMINISTRATORS)
