"""Agent模型调用的线程安全临时收集器。"""

from dataclasses import dataclass
from threading import Lock

from app.modules.rag.ports import ModelUsage


@dataclass(frozen=True, slots=True)
class AgentModelUsageObservation:
    sequence: int
    operation: str
    usage: ModelUsage


class AgentModelUsageCollector:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_sequence = 1
        self._items: list[AgentModelUsageObservation] = []

    def add(self, operation: str, usage: ModelUsage) -> None:
        with self._lock:
            self._items.append(
                AgentModelUsageObservation(
                    sequence=self._next_sequence,
                    operation=operation,
                    usage=usage,
                )
            )
            self._next_sequence += 1

    def drain(self) -> list[AgentModelUsageObservation]:
        with self._lock:
            items = self._items
            self._items = []
            return items
