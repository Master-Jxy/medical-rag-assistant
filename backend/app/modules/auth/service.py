"""用户注册和登录用例；路由只负责收发参数，不直接读写数据库。"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.auth.passwords import hash_password, verify_password
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import LoginRequest, UserCreate, UserResponse


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


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = UserRepository(session)

    def register(self, request: UserCreate) -> UserResponse:
        email = str(request.email).lower()
        if self.repository.get_by_email(email) is not None:
            raise EmailAlreadyRegisteredError()

        user = User(
            email=email,
            display_name=request.display_name,
            password_hash=hash_password(request.password.get_secret_value()),
            role="user",
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

    def authenticate(self, request: LoginRequest) -> UserResponse:
        """邮箱不存在、密码错误或账号停用都返回同一种安全提示。"""
        user = self.repository.get_by_email(str(request.email).lower())
        password = request.password.get_secret_value()
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        return UserResponse.model_validate(user)
