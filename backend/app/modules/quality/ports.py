"""质量模块读取会话上下文的公开契约。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReviewMessageContext:
    message_id: str
    conversation_id: str
    question_excerpt: str
    answer_excerpt: str
    source_names: tuple[str, ...]


class ConversationQualityPort(Protocol):
    def user_owns_completed_answer(self, user_id: str, message_id: str) -> bool: ...

    def get_review_context(self, message_id: str) -> ReviewMessageContext | None: ...
