"""用户注册和登录用例；路由只负责收发参数，不直接读写数据库。"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.auth.models import User, utc_now
from app.modules.auth.email_verification import (
    EmailVerificationService,
    InvalidEmailVerificationCodeError,
)
from app.modules.auth.ports import VerificationPurpose
from app.modules.auth.passwords import hash_password, verify_password
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import (
    AuthenticatedUser,
    LoginRequest,
    PasswordResetConfirm,
    UserCreate,
    UserResponse,
)


class EmailAlreadyRegisteredError(AppError):
    def __init__(self) -> None:
        super().__init__("该邮箱已注册", code="EMAIL_ALREADY_REGISTERED", status_code=409)


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "邮箱或密码错误",
            code="INVALID_CREDENTIALS",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidAuthTokenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "登录凭证无效或已过期",
            code="INVALID_AUTH_TOKEN",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )


class AdminRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__("需要管理员权限", code="ADMIN_REQUIRED", status_code=403)


class RoleRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__("当前账号没有所需权限", code="ROLE_REQUIRED", status_code=403)


class UserService:
    def __init__(
        self,
        session: Session,
        email_verification: EmailVerificationService,
    ) -> None:
        self.session = session
        self.repository = UserRepository(session)
        self.email_verification = email_verification

    def request_registration_code(self, email: str) -> None:
        self.email_verification.request_code(
            email=email,
            purpose=VerificationPurpose.REGISTER,
            should_send=self.repository.get_by_email(email) is None,
        )

    def register(self, request: UserCreate) -> UserResponse:
        email = str(request.email).lower()
        if self.repository.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError()
        self.email_verification.consume_code(
            email=email,
            purpose=VerificationPurpose.REGISTER,
            code=request.verification_code,
        )

        user = User(
            email=email,
            display_name=request.display_name,
            password_hash=hash_password(request.password.get_secret_value()),
            role="user",
            email_verified_at=utc_now(),
        )
        try:
            self.repository.add(user)
            self.session.commit()
            self.session.refresh(user)
        except IntegrityError as exc:
            # 预检查后仍可能发生并发竞争，数据库唯一约束是最后防线。
            self.session.rollback()
            raise EmailAlreadyRegisteredError() from exc
        return UserResponse.model_validate(user)

    def request_password_reset(self, email: str) -> None:
        user = self.repository.get_by_email(email)
        try:
            self.email_verification.request_code(
                email=email,
                purpose=VerificationPurpose.PASSWORD_RESET,
                should_send=user is not None and user.is_active,
            )
        except AppError:
            # 请求端始终使用统一公开响应，避免利用基础设施状态枚举账号。
            return

    def confirm_password_reset(self, request: PasswordResetConfirm) -> None:
        email = str(request.email).lower()
        self.email_verification.consume_code(
            email=email,
            purpose=VerificationPurpose.PASSWORD_RESET,
            code=request.verification_code,
        )
        try:
            user = self.repository.get_by_email_for_update(email)
            if user is None or not user.is_active:
                self.session.rollback()
                raise InvalidEmailVerificationCodeError()
            self.repository.reset_password(
                user,
                password_hash=hash_password(
                    request.new_password.get_secret_value()
                ),
            )
            self.session.commit()
        except InvalidEmailVerificationCodeError:
            raise
        except Exception:
            self.session.rollback()
            raise

    def authenticate(self, request: LoginRequest) -> AuthenticatedUser:
        """邮箱不存在、密码错误或账号停用都返回同一种安全提示。"""
        user = self.repository.get_by_email(str(request.email).lower())
        password = request.password.get_secret_value()
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        return AuthenticatedUser.model_validate(user)
