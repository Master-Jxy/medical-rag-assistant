"""Redis 故障时使用的有界进程内并发占位适配器。"""

from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Callable

from app.ports.concurrency_limit import ConcurrencyLimitDecision


class BoundedLocalConcurrencyLimitAdapter:
    def __init__(
        self,
        max_keys: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.max_keys = max_keys
        self.clock = clock
        self._entries: OrderedDict[str, dict[str, float]] = OrderedDict()
        self._lock = Lock()

    def acquire(
        self,
        key: str,
        owner_token: str,
        limit: int,
        ttl_seconds: int,
    ) -> ConcurrencyLimitDecision:
        now = self.clock()
        with self._lock:
            self._remove_expired(now)
            owners = self._entries.get(key)
            if owners is None:
                if len(self._entries) >= self.max_keys:
                    retry_after = min(
                        max(1, int(expiry - now + 0.999))
                        for entry in self._entries.values()
                        for expiry in entry.values()
                    )
                    return ConcurrencyLimitDecision(False, retry_after)
                owners = {}
                self._entries[key] = owners
            else:
                self._entries.move_to_end(key)

            if len(owners) >= limit:
                retry_after = min(
                    max(1, int(expiry - now + 0.999))
                    for expiry in owners.values()
                )
                return ConcurrencyLimitDecision(False, retry_after)

            owners[owner_token] = now + ttl_seconds
            return ConcurrencyLimitDecision(True, ttl_seconds)

    def release(self, key: str, owner_token: str) -> bool:
        with self._lock:
            owners = self._entries.get(key)
            if owners is None or owner_token not in owners:
                return False
            owners.pop(owner_token)
            if not owners:
                self._entries.pop(key, None)
            return True

    def _remove_expired(self, now: float) -> None:
        empty_keys: list[str] = []
        for key, owners in self._entries.items():
            expired = [token for token, expiry in owners.items() if expiry <= now]
            for token in expired:
                owners.pop(token, None)
            if not owners:
                empty_keys.append(key)
        for key in empty_keys:
            self._entries.pop(key, None)
