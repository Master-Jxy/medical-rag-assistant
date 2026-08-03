"""Agent模型调用的线程安全临时收集器。"""

from dataclasses import dataclass
from threading import Lock

from app.modules.rag.ports import ModelUsage


class AgentModelCallBudgetExceeded(RuntimeError):
    pass


class AgentModelCallBudget:
    """一次运行共享的模型调用硬闸门。"""

    def __init__(self, max_calls: int = 4) -> None:
        if not 1 <= max_calls <= 8:
            raise ValueError("Agent模型调用上限必须位于1到8之间")
        self.max_calls = max_calls
        self._used_calls = 0
        self._lock = Lock()

    @property
    def used_calls(self) -> int:
        with self._lock:
            return self._used_calls

    def acquire(self, operation: str) -> int:
        del operation
        with self._lock:
            if self._used_calls >= self.max_calls:
                raise AgentModelCallBudgetExceeded("Agent模型调用次数已达到上限")
            self._used_calls += 1
            return self._used_calls


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
