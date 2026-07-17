"""并发占位端口：支持容量、TTL 和带所有权令牌的安全释放。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConcurrencyLimitDecision:
    acquired: bool
    retry_after_seconds: int


class ConcurrencyLimitBackendUnavailable(RuntimeError):
    """并发占位后端当前不可用。"""


class ConcurrencyLimitPort(Protocol):
    def acquire(
        self,
        key: str,
        owner_token: str,
        limit: int,
        ttl_seconds: int,
    ) -> ConcurrencyLimitDecision: ...

    def release(self, key: str, owner_token: str) -> bool: ...
