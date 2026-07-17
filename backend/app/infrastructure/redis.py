"""Redis 连接适配器：集中封装创建、ping、失败降级和关闭。"""

import logging
from enum import StrEnum
from threading import Lock
from typing import Callable, Protocol

from redis import Redis

from app.core.config import Settings
from app.ports.distributed_lock import DistributedLockBackendUnavailable
from app.ports.idempotency import (
    IdempotencyBackendUnavailable,
    IdempotencyRecord,
    IdempotencyStatus,
)
from app.ports.concurrency_limit import (
    ConcurrencyLimitBackendUnavailable,
    ConcurrencyLimitDecision,
)
from app.ports.rate_limit import RateLimitBackendUnavailable, RateLimitDecision

logger = logging.getLogger(__name__)


class RedisHealthStatus(StrEnum):
    OK = "ok"
    DISABLED = "disabled"
    DEGRADED = "degraded"


class RedisClient(Protocol):
    def ping(self) -> bool: ...

    def close(self) -> None: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


RedisClientFactory = Callable[..., RedisClient]


class RedisInfrastructure:
    """惰性创建客户端；每次健康检查最多尝试一次，不进行内部重试。"""

    def __init__(
        self,
        settings: Settings,
        client_factory: RedisClientFactory = Redis.from_url,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self._client: RedisClient | None = None
        self._client_lock = Lock()
        self._runtime_degraded = False

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        """通过单条 Lua 脚本原子完成计数和 TTL 设置。"""
        script = """
        local current = redis.call('INCR', KEYS[1])
        if current == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
        end
        local ttl = redis.call('TTL', KEYS[1])
        if ttl < 0 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
            ttl = tonumber(ARGV[1])
        end
        return {current, ttl}
        """
        if self.settings.optional_redis_url() is None:
            raise RateLimitBackendUnavailable("Redis is disabled")
        try:
            result = self._get_client().eval(script, 1, key, window_seconds)
            current, ttl = result  # type: ignore[misc]
            self._runtime_degraded = False
            return RateLimitDecision(int(current) <= limit, max(1, int(ttl)))
        except Exception as exc:
            should_log = not self._runtime_degraded
            self._runtime_degraded = True
            self._discard_client()
            if should_log:
                logger.warning(
                    "Redis rate limit command failed",
                    extra={"redis_error_type": type(exc).__name__},
                )
            raise RateLimitBackendUnavailable("Redis rate limiter unavailable") from exc

    def acquire(
        self,
        key: str,
        owner_token: str,
        limit: int,
        ttl_seconds: int,
    ) -> ConcurrencyLimitDecision:
        """使用 Redis 有序集合原子清理过期占位并尝试获取容量。"""
        script = """
        local redis_time = redis.call('TIME')
        local now = tonumber(redis_time[1])
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
        local count = redis.call('ZCARD', KEYS[1])
        if count >= tonumber(ARGV[2]) then
            local earliest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
            local retry_after = math.max(1, math.ceil(tonumber(earliest[2]) - now))
            return {0, retry_after}
        end
        redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[1])
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
        return {1, tonumber(ARGV[3])}
        """
        if self.settings.optional_redis_url() is None:
            raise ConcurrencyLimitBackendUnavailable("Redis is disabled")
        try:
            result = self._get_client().eval(
                script, 1, key, owner_token, limit, ttl_seconds
            )
            acquired, retry_after = result  # type: ignore[misc]
            self._runtime_degraded = False
            return ConcurrencyLimitDecision(
                bool(int(acquired)), max(1, int(retry_after))
            )
        except Exception as exc:
            self._mark_command_failure("Redis concurrency acquire failed", exc)
            raise ConcurrencyLimitBackendUnavailable(
                "Redis concurrency limiter unavailable"
            ) from exc

    def release(self, key: str, owner_token: str) -> bool:
        """只释放匹配所有权令牌的占位，避免删除其他请求。"""
        script = """
        local removed = redis.call('ZREM', KEYS[1], ARGV[1])
        if redis.call('ZCARD', KEYS[1]) == 0 then
            redis.call('DEL', KEYS[1])
        end
        return removed
        """
        if self.settings.optional_redis_url() is None:
            raise ConcurrencyLimitBackendUnavailable("Redis is disabled")
        try:
            removed = self._get_client().eval(script, 1, key, owner_token)
            self._runtime_degraded = False
            return bool(int(removed))
        except Exception as exc:
            self._mark_command_failure("Redis concurrency release failed", exc)
            raise ConcurrencyLimitBackendUnavailable(
                "Redis concurrency limiter unavailable"
            ) from exc

    def acquire_lock(self, key: str, owner_token: str, ttl_seconds: int) -> bool:
        """用 SET NX EX 原子获取带所有权令牌和 TTL 的互斥锁。"""
        script = """
        local result = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2])
        if result then
            return 1
        end
        return 0
        """
        if self.settings.optional_redis_url() is None:
            raise DistributedLockBackendUnavailable("Redis is disabled")
        try:
            acquired = self._get_client().eval(
                script, 1, key, owner_token, ttl_seconds
            )
            self._runtime_degraded = False
            return bool(int(acquired))
        except Exception as exc:
            self._mark_command_failure("Redis distributed lock acquire failed", exc)
            raise DistributedLockBackendUnavailable(
                "Redis distributed lock unavailable"
            ) from exc

    def release_lock(self, key: str, owner_token: str) -> bool:
        """原子比较所有权令牌，只删除当前请求持有的锁。"""
        script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """
        if self.settings.optional_redis_url() is None:
            raise DistributedLockBackendUnavailable("Redis is disabled")
        try:
            released = self._get_client().eval(script, 1, key, owner_token)
            self._runtime_degraded = False
            return bool(int(released))
        except Exception as exc:
            self._mark_command_failure("Redis distributed lock release failed", exc)
            raise DistributedLockBackendUnavailable(
                "Redis distributed lock unavailable"
            ) from exc

    def begin_idempotency(
        self, key: str, fingerprint: str, ttl_seconds: int
    ) -> IdempotencyRecord:
        """原子创建进行中记录，或读取已存在请求的稳定状态。"""
        script = """
        if redis.call('EXISTS', KEYS[1]) == 0 then
            redis.call('HSET', KEYS[1], 'state', 'in_progress', 'fingerprint', ARGV[1])
            redis.call('EXPIRE', KEYS[1], ARGV[2])
            return {'started'}
        end
        if redis.call('HGET', KEYS[1], 'fingerprint') ~= ARGV[1] then
            return {'conflict'}
        end
        local state = redis.call('HGET', KEYS[1], 'state')
        if state == 'completed' then
            return {
                'completed',
                redis.call('HGET', KEYS[1], 'request_id') or '',
                redis.call('HGET', KEYS[1], 'conversation_id') or '',
                redis.call('HGET', KEYS[1], 'user_message_id') or '',
                redis.call('HGET', KEYS[1], 'assistant_message_id') or ''
            }
        end
        return {'in_progress'}
        """
        if self.settings.optional_redis_url() is None:
            raise IdempotencyBackendUnavailable("Redis is disabled")
        try:
            result = self._get_client().eval(script, 1, key, fingerprint, ttl_seconds)
            values = list(result)  # type: ignore[arg-type]
            status = IdempotencyStatus(str(values[0]))
            self._runtime_degraded = False
            if status is IdempotencyStatus.COMPLETED:
                return IdempotencyRecord(
                    status,
                    request_id=str(values[1]),
                    conversation_id=str(values[2]),
                    user_message_id=str(values[3]),
                    assistant_message_id=str(values[4]),
                )
            return IdempotencyRecord(status)
        except IdempotencyBackendUnavailable:
            raise
        except Exception as exc:
            self._mark_command_failure("Redis idempotency begin failed", exc)
            raise IdempotencyBackendUnavailable(
                "Redis idempotency unavailable"
            ) from exc

    def complete_idempotency(
        self,
        key: str,
        fingerprint: str,
        *,
        request_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        ttl_seconds: int,
    ) -> bool:
        script = """
        if redis.call('HGET', KEYS[1], 'fingerprint') ~= ARGV[1] then
            return 0
        end
        if redis.call('HGET', KEYS[1], 'state') ~= 'in_progress' then
            return 0
        end
        redis.call('HSET', KEYS[1],
            'state', 'completed',
            'request_id', ARGV[2],
            'conversation_id', ARGV[3],
            'user_message_id', ARGV[4],
            'assistant_message_id', ARGV[5])
        redis.call('EXPIRE', KEYS[1], ARGV[6])
        return 1
        """
        if self.settings.optional_redis_url() is None:
            raise IdempotencyBackendUnavailable("Redis is disabled")
        try:
            result = self._get_client().eval(
                script,
                1,
                key,
                fingerprint,
                request_id,
                conversation_id,
                user_message_id,
                assistant_message_id,
                ttl_seconds,
            )
            self._runtime_degraded = False
            return bool(int(result))
        except Exception as exc:
            self._mark_command_failure("Redis idempotency complete failed", exc)
            raise IdempotencyBackendUnavailable(
                "Redis idempotency unavailable"
            ) from exc

    def clear_idempotency(self, key: str, fingerprint: str) -> bool:
        script = """
        if redis.call('HGET', KEYS[1], 'fingerprint') == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """
        if self.settings.optional_redis_url() is None:
            raise IdempotencyBackendUnavailable("Redis is disabled")
        try:
            result = self._get_client().eval(script, 1, key, fingerprint)
            self._runtime_degraded = False
            return bool(int(result))
        except Exception as exc:
            self._mark_command_failure("Redis idempotency cleanup failed", exc)
            raise IdempotencyBackendUnavailable(
                "Redis idempotency unavailable"
            ) from exc

    def health_status(self) -> RedisHealthStatus:
        if self.settings.optional_redis_url() is None:
            return RedisHealthStatus.DISABLED

        try:
            status = (
                RedisHealthStatus.OK
                if self._get_client().ping()
                else RedisHealthStatus.DEGRADED
            )
            self._runtime_degraded = status is RedisHealthStatus.DEGRADED
            return status
        except Exception as exc:
            should_log = not self._runtime_degraded
            self._runtime_degraded = True
            self._discard_client()
            if should_log:
                logger.warning(
                    "Redis health check failed",
                    extra={"redis_error_type": type(exc).__name__},
                )
            return RedisHealthStatus.DEGRADED

    def close(self) -> None:
        self._discard_client()

    def _mark_command_failure(self, message: str, exc: Exception) -> None:
        should_log = not self._runtime_degraded
        self._runtime_degraded = True
        self._discard_client()
        if should_log:
            logger.warning(
                message,
                extra={"redis_error_type": type(exc).__name__},
            )

    def _get_client(self) -> RedisClient:
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is None:
                redis_url = self.settings.optional_redis_url()
                if redis_url is None:
                    raise RuntimeError("Redis is disabled")
                self._client = self.client_factory(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
                    socket_timeout=self.settings.redis_socket_timeout_seconds,
                    retry_on_timeout=False,
                )
        return self._client

    def _discard_client(self) -> None:
        with self._client_lock:
            client, self._client = self._client, None
        if client is None:
            return
        try:
            client.close()
        except Exception as exc:
            logger.warning(
                "Redis client close failed",
                extra={"redis_error_type": type(exc).__name__},
            )
