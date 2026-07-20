"""用于验证 Runner 的确定性假适配器，不导入任何真实基础设施。"""

from app.evaluation.ports import (
    AnswerObservation,
    EvaluationQuery,
    RetrievalObservation,
    TokenUsageObservation,
)
from app.evaluation.schemas import EvaluationSet, ExpectedBehavior


class FakeRetrievalError(RuntimeError):
    pass


class FakeAnswerError(RuntimeError):
    pass


class FixedFakeRetrievalAdapter:
    adapter_name = "fixed_fake_retrieval_v1"

    def __init__(
        self,
        evaluation_set: EvaluationSet,
        *,
        failure_case_ids: set[str] | None = None,
        source_overrides: dict[str, tuple[str, ...]] | None = None,
        latency_ms: float = 4.0,
    ) -> None:
        self.sources = {
            case.case_id: tuple(case.expected_source_document_ids)
            for case in evaluation_set.cases
        }
        self.failure_case_ids = failure_case_ids or set()
        self.source_overrides = source_overrides or {}
        self.latency_ms = latency_ms

    def retrieve(self, query: EvaluationQuery) -> RetrievalObservation:
        if query.case_id in self.failure_case_ids:
            raise FakeRetrievalError()
        return RetrievalObservation(
            source_document_ids=self.source_overrides.get(
                query.case_id, self.sources[query.case_id]
            ),
            latency_ms=self.latency_ms,
        )

class FixedFakeAnswerAdapter:
    adapter_name = "fixed_fake_answer_v1"

    def __init__(
        self,
        evaluation_set: EvaluationSet,
        *,
        failure_case_ids: set[str] | None = None,
        usage_missing_case_ids: set[str] | None = None,
        behavior_overrides: dict[str, ExpectedBehavior] | None = None,
        answer_text_overrides: dict[str, str] | None = None,
        latency_ms: float = 8.0,
    ) -> None:
        self.behaviors = {
            case.case_id: case.expected_behavior for case in evaluation_set.cases
        }
        self.answers = {
            case.case_id: " ".join(case.expected_key_facts)
            for case in evaluation_set.cases
        }
        self.failure_case_ids = failure_case_ids or set()
        self.usage_missing_case_ids = usage_missing_case_ids or set()
        self.behavior_overrides = behavior_overrides or {}
        self.answer_text_overrides = answer_text_overrides or {}
        self.latency_ms = latency_ms

    def answer(
        self, query: EvaluationQuery, source_document_ids: tuple[str, ...]
    ) -> AnswerObservation:
        del source_document_ids
        if query.case_id in self.failure_case_ids:
            raise FakeAnswerError()
        usage = None
        if query.case_id not in self.usage_missing_case_ids:
            usage = TokenUsageObservation(
                input_tokens=100,
                output_tokens=50,
                estimated_cost_cny=0.001,
            )
        return AnswerObservation(
            behavior=self.behavior_overrides.get(
                query.case_id, self.behaviors[query.case_id]
            ),
            answer_text=self.answer_text_overrides.get(
                query.case_id, self.answers[query.case_id]
            ),
            latency_ms=self.latency_ms,
            usage=usage,
        )
