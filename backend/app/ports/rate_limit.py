"""限流存储端口；业务层不接触 Redis 客户端或命令。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class RateLimitBackendUnavailable(RuntimeError):
    """计数后端当前不可用，调用方应执行明确的安全降级。"""


class RateLimitPort(Protocol):
    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision: ...
