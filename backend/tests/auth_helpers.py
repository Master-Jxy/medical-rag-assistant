"""会话接口测试共用的用户与短期 JWT 工具。"""

from sqlalchemy.orm import sessionmaker

from app.modules.auth.models import User
from app.modules.auth.tokens import TokenService

TEST_TOKEN_SERVICE = TokenService(
    "conversation-tests-only-secret-longer-than-32-characters",
    expire_minutes=30,
)


def create_test_user(factory: sessionmaker, suffix: str, role: str = "user") -> User:
    with factory() as session:
        user = User(
            email=f"{suffix}@example.com",
            display_name=f"测试用户{suffix}",
            password_hash="not-used-by-conversation-tests",
            role=role,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def auth_headers(user_id: str) -> dict[str, str]:
    token = TEST_TOKEN_SERVICE.create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}
