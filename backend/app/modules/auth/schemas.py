"""认证模块的输入和输出契约，密码与令牌不会出现在用户响应中。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.modules.auth.ports import VerificationPurpose
from app.modules.auth.roles import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)
    verification_code: str = Field(pattern=r"^\d{6}$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class EmailVerificationRequest(BaseModel):
    email: EmailStr
    purpose: VerificationPurpose

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class PublicMessageResponse(BaseModel):
    message: str


class PasswordResetRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    verification_code: str = Field(pattern=r"^\d{6}$")
    new_password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None
    is_active: bool
    role: UserRole
    created_at: datetime
    updated_at: datetime


class AuthenticatedUser(UserResponse):
    token_version: int


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    offset: int
    limit: int


class UserRoleUpdate(BaseModel):
    role: UserRole

    @field_validator("role")
    @classmethod
    def allow_http_managed_roles(cls, value: UserRole) -> UserRole:
        if value is UserRole.SUPER_ADMIN:
            raise ValueError("HTTP接口不允许授予super_admin")
        return value


class UserStatusUpdate(BaseModel):
    is_active: bool
