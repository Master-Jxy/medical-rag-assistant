"""认证 API：注册、登录和读取当前用户。"""

from fastapi import APIRouter, Depends, status

from app.modules.auth.dependencies import (
    get_auth_rate_limit_service,
    get_client_address,
    get_current_user,
    get_user_service,
)
from app.modules.auth.rate_limit import AuthRateLimitService
from app.modules.auth.schemas import LoginRequest, TokenResponse, UserCreate, UserResponse
from app.modules.auth.service import UserService
from app.modules.auth.tokens import TokenService, get_token_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: UserCreate,
    client_address: str = Depends(get_client_address),
    rate_limiter: AuthRateLimitService = Depends(get_auth_rate_limit_service),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    rate_limiter.check_register(client_address)
    return service.register(request)


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    client_address: str = Depends(get_client_address),
    rate_limiter: AuthRateLimitService = Depends(get_auth_rate_limit_service),
    service: UserService = Depends(get_user_service),
    token_service: TokenService = Depends(get_token_service),
) -> TokenResponse:
    rate_limiter.check_login(client_address)
    user = service.authenticate(request)
    return TokenResponse(
        access_token=token_service.create_access_token(user.id),
        expires_in=token_service.expires_in_seconds,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current_user
