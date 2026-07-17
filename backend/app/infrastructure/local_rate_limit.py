"""进程内限流适配器：只作为 Redis 故障时的有界、自动过期保护。"""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable

from app.ports.rate_limit import RateLimitDecision


@dataclass
class _Entry:
    count: int
    expires_at: float


class BoundedLocalRateLimitAdapter:
    def __init__(
        self,
        max_keys: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.max_keys = max_keys
        self.clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = Lock()

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self.clock()
        with self._lock:
            self._remove_expired(now)
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self.max_keys:
                    retry_after = min(
                        max(1, int(item.expires_at - now + 0.999))
                        for item in self._entries.values()
                    )
                    return RateLimitDecision(False, retry_after)
                entry = _Entry(count=0, expires_at=now + window_seconds)
                self._entries[key] = entry
            else:
                self._entries.move_to_end(key)

            entry.count += 1
            retry_after = max(1, int(entry.expires_at - now + 0.999))
            return RateLimitDecision(entry.count <= limit, retry_after)

    def _remove_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
