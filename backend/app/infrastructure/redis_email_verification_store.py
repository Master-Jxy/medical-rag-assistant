"""Redis邮箱验证码存储：所有状态转换均由单条Lua脚本原子完成。"""

from threading import Lock
from typing import Callable

from redis import Redis

from app.core.config import Settings
from app.modules.auth.ports import (
    ChallengeConsumeResult,
    ChallengeCreateResult,
    EmailVerificationBackendUnavailable,
)


class RedisEmailVerificationStore:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., object] = Redis.from_url,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self._client: object | None = None
        self._lock = Lock()

    def create_challenge(
        self,
        *,
        key: str,
        code_digest: str,
        ttl_seconds: int,
        resend_seconds: int,
    ) -> ChallengeCreateResult:
        script = """
        local redis_time = redis.call('TIME')
        local now = tonumber(redis_time[1])
        local resend_at = tonumber(redis.call('HGET', KEYS[1], 'resend_at') or '0')
        if redis.call('EXISTS', KEYS[1]) == 1 and now < resend_at then
            return 0
        end
        redis.call('HSET', KEYS[1],
            'code_digest', ARGV[1],
            'failed_attempts', 0,
            'resend_at', now + tonumber(ARGV[3]))
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        return 1
        """
        result = self._eval(
            script, key, code_digest, ttl_seconds, resend_seconds
        )
        return (
            ChallengeCreateResult.CREATED
            if int(result)
            else ChallengeCreateResult.COOLDOWN
        )

    def consume_challenge(
        self,
        *,
        key: str,
        code_digest: str,
        max_attempts: int,
    ) -> ChallengeConsumeResult:
        script = """
        if redis.call('EXISTS', KEYS[1]) == 0 then
            return 0
        end
        if redis.call('HGET', KEYS[1], 'code_digest') == ARGV[1] then
            redis.call('DEL', KEYS[1])
            return 1
        end
        local attempts = redis.call('HINCRBY', KEYS[1], 'failed_attempts', 1)
        if attempts >= tonumber(ARGV[2]) then
            redis.call('DEL', KEYS[1])
            return 3
        end
        return 2
        """
        result = int(self._eval(script, key, code_digest, max_attempts))
        return {
            0: ChallengeConsumeResult.EXPIRED,
            1: ChallengeConsumeResult.CONSUMED,
            2: ChallengeConsumeResult.INVALID,
            3: ChallengeConsumeResult.ATTEMPTS_EXHAUSTED,
        }[result]

    def delete_challenge(self, *, key: str) -> None:
        self._eval("return redis.call('DEL', KEYS[1])", key)

    def close(self) -> None:
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                client.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _eval(self, script: str, key: str, *args: object) -> object:
        if self.settings.optional_redis_url() is None:
            raise EmailVerificationBackendUnavailable("Redis is disabled")
        try:
            return self._get_client().eval(script, 1, key, *args)  # type: ignore[attr-defined]
        except Exception as exc:
            self.close()
            raise EmailVerificationBackendUnavailable(
                "Email verification store unavailable"
            ) from exc

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is None:
                redis_url = self.settings.optional_redis_url()
                if redis_url is None:
                    raise EmailVerificationBackendUnavailable("Redis is disabled")
                self._client = self.client_factory(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
                    socket_timeout=self.settings.redis_socket_timeout_seconds,
                    retry_on_timeout=False,
                )
        return self._client
