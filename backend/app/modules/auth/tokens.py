"""短期 Bearer JWT 的签发和校验；令牌只包含识别用户所需的最少字段。"""

from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import get_settings
from app.core.exceptions import ConfigurationError
from app.modules.auth.service import InvalidAuthTokenError


class TokenService:
    def __init__(self, secret_key: str, algorithm: str = "HS256", expire_minutes: int = 30) -> None:
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes

    @property
    def expires_in_seconds(self) -> int:
        return self.expire_minutes * 60

    def create_access_token(
        self, user_id: str, *, expires_delta: timedelta | None = None
    ) -> str:
        now = datetime.now(timezone.utc)
        expires_at = now + (expires_delta or timedelta(minutes=self.expire_minutes))
        payload = {
            "sub": user_id,
            "type": "access",
            "iat": now,
            "exp": expires_at,
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_access_token(self, token: str) -> str:
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"require": ["sub", "iat", "exp"]},
            )
            user_id = payload.get("sub")
            if not isinstance(user_id, str) or not user_id or payload.get("type") != "access":
                raise InvalidAuthTokenError()
            return user_id
        except InvalidAuthTokenError:
            raise
        except (InvalidTokenError, TypeError, ValueError) as exc:
            raise InvalidAuthTokenError() from exc


def get_token_service() -> TokenService:
    settings = get_settings()
    try:
        secret_key = settings.require_jwt_secret_key()
    except ValueError as exc:
        raise ConfigurationError("认证服务尚未配置") from exc
    return TokenService(
        secret_key=secret_key,
        algorithm=settings.jwt_algorithm,
        expire_minutes=settings.jwt_expire_minutes,
    )
