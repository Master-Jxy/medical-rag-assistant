"""FastAPI 认证依赖：从 Authorization 头解析当前登录用户。"""

from ipaddress import ip_address

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.core.config import Settings, get_settings
from app.modules.auth.rate_limit import AuthRateLimitService
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import UserResponse
from app.modules.auth.service import AdminRequiredError, InvalidAuthTokenError, UserService
from app.modules.auth.tokens import TokenService, get_token_service

bearer_scheme = HTTPBearer(auto_error=False)


def get_user_service(session: Session = Depends(get_db_session)) -> UserService:
    return UserService(session)


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
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
    token_service: TokenService = Depends(get_token_service),
) -> UserResponse:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidAuthTokenError()

    user_id = token_service.decode_access_token(credentials.credentials)
    user = UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise InvalidAuthTokenError()
    return UserResponse.model_validate(user)


def require_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """集中校验管理员权限；角色以本次请求查询到的数据库记录为准。"""
    if current_user.role != "admin":
        raise AdminRequiredError()
    return current_user
