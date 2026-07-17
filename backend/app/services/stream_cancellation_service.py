"""进程内流式任务取消登记：让停止按钮获得后端确认，而不依赖断网感知。"""

import hashlib
from dataclasses import dataclass
from threading import Event, Lock

from fastapi import Request


@dataclass(frozen=True)
class StreamCancellationLease:
    key: str
    event: Event


class StreamCancellationService:
    """登记当前进程的流式任务；业务键只保存摘要。"""

    def __init__(self) -> None:
        self._active: dict[str, Event] = {}
        self._lock = Lock()

    @staticmethod
    def _key(user_id: str, conversation_id: str, client_request_id: str) -> str:
        return hashlib.sha256(
            f"{user_id}:{conversation_id}:{client_request_id}".encode("utf-8")
        ).hexdigest()

    def register(
        self, user_id: str, conversation_id: str, client_request_id: str
    ) -> StreamCancellationLease:
        key = self._key(user_id, conversation_id, client_request_id)
        event = Event()
        with self._lock:
            self._active[key] = event
        return StreamCancellationLease(key, event)

    def request_stop(
        self, user_id: str, conversation_id: str, client_request_id: str
    ) -> bool:
        key = self._key(user_id, conversation_id, client_request_id)
        with self._lock:
            event = self._active.get(key)
        if event is None:
            return False
        event.set()
        return True

    def unregister(self, lease: StreamCancellationLease) -> None:
        with self._lock:
            if self._active.get(lease.key) is lease.event:
                self._active.pop(lease.key, None)


def get_stream_cancellation_service(request: Request) -> StreamCancellationService:
    return request.app.state.stream_cancellation_service
