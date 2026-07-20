"""离线评估 Runner 使用的小型 Port，不暴露任何厂商 SDK。"""

from dataclasses import dataclass
from typing import Protocol

from app.evaluation.schemas import ExpectedBehavior


@dataclass(frozen=True)
class EvaluationQuery:
    case_id: str
    question: str
    history: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RetrievalObservation:
    source_document_ids: tuple[str, ...]
    latency_ms: float


@dataclass(frozen=True)
class TokenUsageObservation:
    input_tokens: int
    output_tokens: int
    estimated_cost_cny: float | None = None


@dataclass(frozen=True)
class AnswerObservation:
    behavior: ExpectedBehavior
    answer_text: str
    latency_ms: float
    usage: TokenUsageObservation | None = None


class EvaluationRetrievalPort(Protocol):
    adapter_name: str

    def retrieve(self, query: EvaluationQuery) -> RetrievalObservation: ...


class EvaluationAnswerPort(Protocol):
    adapter_name: str

    def answer(
        self, query: EvaluationQuery, source_document_ids: tuple[str, ...]
    ) -> AnswerObservation: ...


class EvaluationRunGuard(Protocol):
    """真实运行的全局预算闸门；假干跑可以不提供。"""

    def before_retrieval(self) -> None: ...

    def before_answer(self) -> None: ...

    def record_answer_usage(self, usage: TokenUsageObservation | None) -> None: ...

    def record_answer_failure(self) -> None: ...
