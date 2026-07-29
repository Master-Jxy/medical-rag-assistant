"""FastAPI 认证依赖：从 Authorization 头解析当前登录用户。"""

from ipaddress import ip_address

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError
from app.modules.auth.rate_limit import AuthRateLimitService
from app.modules.auth.email_verification import EmailVerificationService
from app.modules.auth.repository import UserRepository
from app.modules.auth.roles import RolePolicy, UserRole
from app.modules.auth.schemas import UserResponse
from app.modules.auth.service import (
    AdminRequiredError,
    InvalidAuthTokenError,
    RoleRequiredError,
    UserService,
)
from app.modules.auth.tokens import TokenService, get_token_service

bearer_scheme = HTTPBearer(auto_error=False)


def get_email_verification_service(request: Request) -> EmailVerificationService:
    try:
        request.app.state.settings.require_jwt_secret_key()
    except ValueError as exc:
        raise ConfigurationError("邮箱验证码服务尚未配置") from exc
    return request.app.state.email_verification_service


def get_user_service(
    session: Session = Depends(get_db_session),
    email_verification: EmailVerificationService = Depends(
        get_email_verification_service
    ),
) -> UserService:
    return UserService(session, email_verification)


def get_auth_rate_limit_service(request: Request) -> AuthRateLimitService:
    return request.app.state.auth_rate_limit_service


def get_client_address(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """默认使用直连地址；仅可信代理可以提供 X-Forwarded-For。"""
    direct = _normalize_address(request.client.host if request.client else None)
    if direct not in set(settings.trusted_proxy_ips):
        return direct

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return _normalize_address(forwarded, fallback=direct)


def _normalize_address(value: str | None, fallback: str = "unknown") -> str:
    if not value:
        return fallback
    try:
        return str(ip_address(value.strip()))
    except ValueError:
        return fallback


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
    token_service: TokenService = Depends(get_token_service),
) -> UserResponse:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidAuthTokenError()

    identity = token_service.decode_access_token(credentials.credentials)
    user = UserRepository(session).get_by_id(identity.user_id)
    if (
        user is None
        or not user.is_active
        or user.token_version != identity.token_version
    ):
        raise InvalidAuthTokenError()
    request.state.user_id = user.id
    return UserResponse.model_validate(user)


def require_roles(
    *allowed_roles: UserRole,
):
    """创建集中角色依赖；调用方声明角色，不自行比较字符串。"""
    if not allowed_roles:
        raise ValueError("require_roles 至少需要一个角色")

    def dependency(
        current_user: UserResponse = Depends(get_current_user),
    ) -> UserResponse:
        if not RolePolicy.allows(current_user.role, allowed_roles):
            raise RoleRequiredError()
        return current_user

    return dependency


def require_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """集中校验管理员权限；角色以本次请求查询到的数据库记录为准。"""
    if not RolePolicy.is_admin(current_user.role):
        raise AdminRequiredError()
    return current_user


require_super_admin = require_roles(UserRole.SUPER_ADMIN)
