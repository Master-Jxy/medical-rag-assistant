"""用户模型和注册服务测试：不调用真实 MySQL、邮件或模型服务。"""

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.core.config import Settings
from app.db.session import build_engine
from app.modules.auth.models import User
from app.modules.auth.passwords import hash_password, verify_password
from app.modules.auth.schemas import UserCreate
from app.modules.auth.service import EmailAlreadyRegisteredError, UserService


def build_auth_engine():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_password_is_hashed_with_argon2_and_can_be_verified() -> None:
    plaintext = "SafePassword_2026!"
    password_hash = hash_password(plaintext)

    assert plaintext not in password_hash
    assert password_hash.startswith("$argon2")
    assert verify_password(plaintext, password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_user_service_normalizes_email_and_never_stores_plaintext_password() -> None:
    engine = build_auth_engine()
    with Session(engine) as session:
        response = UserService(session).register(
            UserCreate(
                email="  STUDENT@Example.COM ",
                password="SafePassword_2026!",
                display_name="  医学资料学习者  ",
            )
        )
        saved = session.scalar(select(User).where(User.id == response.id))

        assert response.email == "student@example.com"
        assert response.display_name == "医学资料学习者"
        assert saved is not None
        assert saved.password_hash != "SafePassword_2026!"
        assert verify_password("SafePassword_2026!", saved.password_hash)


def test_user_service_rejects_duplicate_email_case_insensitively() -> None:
    engine = build_auth_engine()
    with Session(engine) as session:
        service = UserService(session)
        service.register(UserCreate(email="user@example.com", password="password-123"))

        with pytest.raises(EmailAlreadyRegisteredError) as exc_info:
            service.register(UserCreate(email="USER@EXAMPLE.COM", password="password-456"))

        assert exc_info.value.code == "EMAIL_ALREADY_REGISTERED"
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_database_unique_constraint_is_the_final_duplicate_guard() -> None:
    engine = build_auth_engine()
    with Session(engine) as session:
        session.add_all(
            [
                User(email="same@example.com", password_hash="hash-1"),
                User(email="same@example.com", password_hash="hash-2"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_jwt_configuration_rejects_short_secret_and_unsupported_algorithm() -> None:
    settings = Settings(_env_file=None, jwt_secret_key="too-short")
    with pytest.raises(ValueError, match="32"):
        settings.require_jwt_secret_key()

    with pytest.raises(ValidationError, match="HS256"):
        Settings(_env_file=None, jwt_algorithm="none")
