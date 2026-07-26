"""资料整理文本生成契约。"""

from dataclasses import dataclass
from typing import Protocol

from app.modules.knowledge.public_ports import PublishedDocumentContent


@dataclass(frozen=True, slots=True)
class GeneratedAgentText:
    content: str
    used_tokens: int = 0
    estimated_cost_cny: float = 0


class AgentContentGeneratorPort(Protocol):
    def summarize(
        self,
        document: PublishedDocumentContent,
        focus: str | None,
    ) -> GeneratedAgentText: ...

    def compare(
        self,
        documents: list[PublishedDocumentContent],
        dimensions: list[str],
    ) -> GeneratedAgentText: ...

    def learning_report(
        self,
        *,
        title: str,
        learning_goal: str,
        documents: list[PublishedDocumentContent],
    ) -> GeneratedAgentText: ...
