"""分布式锁端口：业务层不直接依赖 redis-py。"""

from typing import Protocol


class DistributedLockBackendUnavailable(RuntimeError):
    """无法确认分布式锁状态。"""


class DistributedLockPort(Protocol):
    def acquire_lock(self, key: str, owner_token: str, ttl_seconds: int) -> bool: ...

    def release_lock(self, key: str, owner_token: str) -> bool: ...
