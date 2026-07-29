"""认证 API：注册、登录和读取当前用户。"""

from fastapi import APIRouter, Depends, status

from app.modules.auth.dependencies import (
    get_auth_rate_limit_service,
    get_client_address,
    get_current_user,
    get_user_service,
)
from app.modules.auth.rate_limit import AuthRateLimitService
from app.modules.auth.schemas import (
    EmailVerificationRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PublicMessageResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from app.modules.auth.service import UserService
from app.modules.auth.tokens import TokenService, get_token_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/email-verification/request",
    response_model=PublicMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_email_verification(
    request: EmailVerificationRequest,
    client_address: str = Depends(get_client_address),
    rate_limiter: AuthRateLimitService = Depends(get_auth_rate_limit_service),
    service: UserService = Depends(get_user_service),
) -> PublicMessageResponse:
    if request.purpose.value != "register":
        # password_reset由16.1c的专用统一响应接口拥有。
        from app.core.exceptions import AppError

        raise AppError(
            "当前验证码用途不受支持",
            code="UNSUPPORTED_VERIFICATION_PURPOSE",
            status_code=422,
        )
    rate_limiter.check_email_verification(
        action="request",
        client_address=client_address,
        email=str(request.email),
    )
    service.request_registration_code(str(request.email))
    return PublicMessageResponse(message="如果该邮箱可用于注册，验证码将发送到邮箱。")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: UserCreate,
    client_address: str = Depends(get_client_address),
    rate_limiter: AuthRateLimitService = Depends(get_auth_rate_limit_service),
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    rate_limiter.check_register(client_address)
    rate_limiter.check_email_verification(
        action="consume",
        client_address=client_address,
        email=str(request.email),
    )
    return service.register(request)


@router.post(
    "/password-reset/request",
    response_model=PublicMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_reset(
    request: PasswordResetRequest,
    client_address: str = Depends(get_client_address),
    rate_limiter: AuthRateLimitService = Depends(get_auth_rate_limit_service),
    service: UserService = Depends(get_user_service),
) -> PublicMessageResponse:
    rate_limiter.check_email_verification(
        action="password-reset-request",
        client_address=client_address,
        email=str(request.email),
    )
    service.request_password_reset(str(request.email))
    return PublicMessageResponse(
        message="如果该邮箱已注册，验证码将发送到邮箱。"
    )


@router.post(
    "/password-reset/confirm",
    response_model=PublicMessageResponse,
)
def confirm_password_reset(
    request: PasswordResetConfirm,
    client_address: str = Depends(get_client_address),
    rate_limiter: AuthRateLimitService = Depends(get_auth_rate_limit_service),
    service: UserService = Depends(get_user_service),
) -> PublicMessageResponse:
    rate_limiter.check_email_verification(
        action="password-reset-confirm",
        client_address=client_address,
        email=str(request.email),
    )
    service.confirm_password_reset(request)
    return PublicMessageResponse(message="密码已重置，请重新登录。")


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
        access_token=token_service.create_access_token(
            user.id,
            token_version=user.token_version,
        ),
        expires_in=token_service.expires_in_seconds,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current_user
