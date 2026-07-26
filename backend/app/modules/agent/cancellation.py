"""进程内Agent主动停止信号；不承载业务主数据。"""

from threading import Lock


class AgentCancellationService:
    def __init__(self) -> None:
        self._requested: set[tuple[str, str]] = set()
        self._lock = Lock()

    def request_stop(self, user_id: str, run_id: str) -> None:
        with self._lock:
            self._requested.add((user_id, run_id))

    def is_requested(self, user_id: str, run_id: str) -> bool:
        with self._lock:
            return (user_id, run_id) in self._requested

    def clear(self, user_id: str, run_id: str) -> None:
        with self._lock:
            self._requested.discard((user_id, run_id))
