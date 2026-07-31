from dataclasses import dataclass
from typing import Protocol

from app.core.enums import StrEnum
from app.modules.usage.contracts import ModelUsage


class MemoryCategory(StrEnum):
    PROFILE = "profile"
    PREFERENCE = "preference"
    GOAL = "goal"
    ONGOING_TASK = "ongoing_task"
    HEALTH_CONTEXT = "health_context"
    EXPLICIT_NOTE = "explicit_note"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class MemoryContextItem:
    id: str
    category: str
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class MemoryContext:
    items: list[MemoryContextItem]
    total_chars: int
    truncated: bool


class MemoryContextProvider(Protocol):
    def search(self, user_id: str, question: str, *, surface: str) -> MemoryContext: ...


class MemoryExtractionModelPort(Protocol):
    def extract(self, messages: list[dict[str, str]]) -> dict: ...
    def drain_usage(self) -> ModelUsage: ...


class MemorySourceReaderPort(Protocol):
    def read_completed(
        self,
        *,
        user_id: str,
        surface: str,
        thread_id: str,
        through_sequence: int,
    ) -> list[dict[str, str]]: ...

    def owns_messages(
        self,
        *,
        user_id: str,
        surface: str,
        thread_id: str,
        message_ids: list[str],
    ) -> bool: ...


class FakeMemoryExtractionModel:
    def __init__(
        self,
        response: dict | None = None,
        usage: ModelUsage | None = None,
    ):
        self.response = response or {"candidates": []}
        self.usage = usage or ModelUsage.not_applicable()
        self.calls = 0

    def extract(self, messages: list[dict[str, str]]) -> dict:
        self.calls += 1
        return self.response

    def drain_usage(self) -> ModelUsage:
        return self.usage


class DisabledMemoryExtractionModel:
    """生产开关关闭时的零调用适配器。"""

    def extract(self, messages: list[dict[str, str]]) -> dict:
        del messages
        return {"candidates": []}

    def drain_usage(self) -> ModelUsage:
        return ModelUsage.not_applicable()
