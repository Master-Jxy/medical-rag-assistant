from argparse import Namespace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from app.core.config import Settings
from app.evaluation.budget import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationBudgetLimits,
)
from app.evaluation.candidate_adapters import CandidateRetrievalAdapter
from app.evaluation.comparison_preflight import run_full_comparison_preflight
from app.evaluation.ports import (
    AnswerObservation,
    EvaluationQuery,
    TokenUsageObservation,
)
from app.evaluation.current_adapters import RetrievedContextStore
from app.evaluation.real_comparison import RealCandidatePorts, build_real_comparison
from app.evaluation.report_schemas import BaselineReport
from app.evaluation.runner import run_evaluation
from app.evaluation.schemas import ExpectedBehavior
from app.modules.rag.ports import RerankResult, RerankUsage
from scripts.preflight_rag_v1_2_comparison import build_plan
from scripts.run_mock_comparison import load_assets
from scripts.run_rag_v1_2_comparison import (
    PAID_CONFIRMATION,
    require_execution_authorization,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def limits(**overrides) -> EvaluationBudgetLimits:
    values = {
        "max_retrieval_calls": 80,
        "max_model_calls": 80,
        "max_total_tokens": 1_480_000,
        "max_estimated_cost_cny": 4.4,
        "embedding_tokens_reserved_per_call": 512,
        "model_input_tokens_reserved_per_call": 9900,
        "model_output_tokens_reserved_per_call": 2048,
        "embedding_price_per_million_tokens_cny": 0.5,
        "model_input_price_per_million_tokens_cny": 2.5,
        "model_output_price_per_million_tokens_cny": 10.0,
        "max_rerank_calls": 40,
        "rerank_tokens_reserved_per_call": 12000,
        "rerank_cost_reserved_per_call_cny": 0.01,
    }
    values.update(overrides)
    return EvaluationBudgetLimits(**values)


class FakeReadOnlyVectorStore:
    def __init__(self) -> None:
        self.vector_calls = []
        self.list_calls = []
        self.documents = [
            Document(
                page_content="心血管资料A",
                metadata={"document_id": "doc-a", "file_name": "A.txt"},
            ),
            Document(
                page_content="心血管资料B",
                metadata={"document_id": "doc-b", "file_name": "B.txt"},
            ),
        ]

    def has_documents(self):
        return True

    def similarity_search(self, query, top_k, metadata_filter=None):
        self.vector_calls.append((query, top_k, metadata_filter))
        return self.documents

    def list_documents(self, metadata_filter=None):
        self.list_calls.append(metadata_filter)
        return [(f"chunk-{index}", doc) for index, doc in enumerate(self.documents)]


class ReverseReranker:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def rerank(self, query, candidates, top_n):
        self.calls.append((query, candidates, top_n))
        if self.error:
            raise self.error
        return RerankResult(
            chunks=list(reversed(candidates[:top_n])),
            usage=RerankUsage(1, 200, 0.00016),
        )


class FixedAnswerAdapter:
    adapter_name = "fixed_answer_v1"

    def answer(self, query, source_document_ids):
        return AnswerObservation(
            behavior=ExpectedBehavior.ANSWER,
            answer_text="固定脱敏回答",
            latency_ms=1.0,
            usage=TokenUsageObservation(100, 20, 0.00045),
        )


class FixedRetrievalAdapter:
    adapter_name = "fixed_retrieval_v1"

    def retrieve(self, query):
        return type(
            "Retrieval",
            (),
            {"source_document_ids": ("doc-a",), "latency_ms": 1.0},
        )()


class FailFirstAnswerAdapter(FixedAnswerAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def answer(self, query, source_document_ids):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("provider failed")
        return super().answer(query, source_document_ids)


def test_read_only_candidate_runs_hybrid_then_one_rerank_and_keeps_context() -> None:
    plan = build_plan()
    profile = next(
        item
        for item in plan.candidate_profiles
        if item.candidate_id == "hybrid_rrf_rerank_v1"
    )
    vector = FakeReadOnlyVectorStore()
    reranker = ReverseReranker()
    context = RetrievedContextStore()
    budget = EvaluationBudget(limits())
    ticks = iter([0.0, 0.1, 0.2, 0.3])
    adapter = CandidateRetrievalAdapter(
        profile=profile,
        vector_store=vector,
        context_store=context,
        budget=budget,
        reranker=reranker,
        clock=lambda: next(ticks),
    )

    result = adapter.retrieve(EvaluationQuery("eval_001", "心血管", ()))

    assert result.source_document_ids == ("doc-b", "doc-a")
    assert result.latency_ms == pytest.approx(300)
    assert len(vector.vector_calls) == 1
    assert len(vector.list_calls) == 1
    assert len(reranker.calls) == 1
    assert [doc.metadata["document_id"] for doc in context.get("eval_001")] == [
        "doc-b",
        "doc-a",
    ]
    observation = adapter.rerank_observations["eval_001"]
    assert observation.external_call is True
    assert observation.succeeded is True
    assert observation.latency_ms == pytest.approx(100)
    assert observation.usage.input_tokens == 200
    assert budget.rerank_calls == 1
    assert budget.rerank_tokens == 200


def test_rerank_failure_is_isolated_with_reserved_budget_and_no_retry() -> None:
    plan = build_plan()
    profile = next(
        item
        for item in plan.candidate_profiles
        if item.candidate_id == "hybrid_rrf_rerank_v1"
    )
    reranker = ReverseReranker(RuntimeError("provider failed"))
    budget = EvaluationBudget(limits())
    adapter = CandidateRetrievalAdapter(
        profile=profile,
        vector_store=FakeReadOnlyVectorStore(),
        context_store=RetrievedContextStore(),
        budget=budget,
        reranker=reranker,
    )

    result = adapter.retrieve(EvaluationQuery("eval_001", "问题", ()))

    assert result.source_document_ids == ("doc-a", "doc-b")
    assert len(reranker.calls) == 1
    assert budget.rerank_calls == 1
    assert budget.rerank_tokens == 12000
    assert adapter.rerank_observations["eval_001"].fallback_used is True
    assert adapter.rerank_observations["eval_001"].usage is None


def test_rerank_budget_stops_before_external_call() -> None:
    budget = EvaluationBudget(limits(max_rerank_calls=1))
    budget.before_rerank()
    budget.record_rerank_usage(
        type("Usage", (), {"input_tokens": 10, "estimated_cost_cny": 0.00001})()
    )

    with pytest.raises(EvaluationBudgetExceeded, match="rerank_call_limit"):
        budget.before_rerank()


def test_full_preflight_checks_snapshot_flags_configuration_and_credentials() -> None:
    evaluation_set, corpus, categories = load_assets()
    settings = Settings(
        dashscope_api_key="test-key",
        rag_hybrid_search_enabled=False,
        rag_rerank_enabled=False,
        rag_min_relevance_score=None,
        rag_filter_department=None,
        rag_filter_topic=None,
        rag_filter_document_type=None,
        rag_filter_knowledge_base_version=None,
    )
    manifest_reader = Mock(return_value=corpus)
    count_reader = Mock(return_value=103)

    report = run_full_comparison_preflight(
        plan=build_plan(),
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        settings=settings,
        current_manifest_reader=manifest_reader,
        collection_count_reader=count_reader,
    )

    assert report.case_count == 40
    assert report.chroma_chunk_count == 103
    assert report.production_flags_disabled is True
    assert report.remote_connectivity_checked is False
    assert report.max_estimated_cost_cny == 4.4
    assert report.expected_cost_min_cny == 0.6
    assert report.expected_cost_max_cny == 1.0
    manifest_reader.assert_called_once_with(corpus.generated_on)
    count_reader.assert_called_once_with(settings)


def test_paid_execution_requires_both_confirmations_and_refuses_overwrite() -> None:
    good = Namespace(
        confirm_paid_run=PAID_CONFIRMATION,
        confirm_plan_sha256="a" * 64,
    )
    require_execution_authorization(
        good,
        plan_sha256="a" * 64,
        output_exists=False,
    )
    with pytest.raises(SystemExit, match="confirm-paid-run"):
        require_execution_authorization(
            Namespace(confirm_paid_run="", confirm_plan_sha256="a" * 64),
            plan_sha256="a" * 64,
            output_exists=False,
        )
    with pytest.raises(SystemExit, match="confirm-plan-sha256"):
        require_execution_authorization(
            Namespace(
                confirm_paid_run=PAID_CONFIRMATION,
                confirm_plan_sha256="0" * 64,
            ),
            plan_sha256="a" * 64,
            output_exists=False,
        )
    with pytest.raises(SystemExit, match="禁止覆盖"):
        require_execution_authorization(
            good,
            plan_sha256="a" * 64,
            output_exists=True,
        )


def test_real_comparison_reuses_frozen_baseline_and_runs_two_candidates() -> None:
    evaluation_set, corpus, categories = load_assets()
    plan = build_plan()
    profiles = {item.candidate_id: item for item in plan.candidate_profiles}
    budget = EvaluationBudget(limits())
    ports = []
    for candidate_id in plan.new_candidate_ids:
        profile = profiles[candidate_id]
        ports.append(
            RealCandidatePorts(
                profile=profile,
                retrieval=CandidateRetrievalAdapter(
                    profile=profile,
                    vector_store=FakeReadOnlyVectorStore(),
                    context_store=RetrievedContextStore(),
                    budget=budget,
                    reranker=(
                        ReverseReranker()
                        if profile.configuration.rerank.enabled
                        else None
                    ),
                ),
                answer=FixedAnswerAdapter(),
            )
        )
    baseline_path = (
        BACKEND_DIR / "evaluation" / "reports" / "current_baseline_v1.json"
    )
    frozen = BaselineReport.model_validate_json(
        baseline_path.read_text(encoding="utf-8")
    )
    original_kind = frozen.run_kind

    report = build_real_comparison(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        baseline_profile=profiles[plan.baseline_candidate_id],
        frozen_baseline=frozen,
        new_candidates=ports,
        budget=budget,
    )

    assert [item.profile.candidate_id for item in report.candidates] == [
        plan.baseline_candidate_id,
        *plan.new_candidate_ids,
    ]
    assert frozen.run_kind == original_kind
    assert budget.retrieval_calls == 80
    assert budget.model_calls == 80
    assert budget.rerank_calls == 40
    assert report.candidates[2].stage_metrics.rerank_external_call_count == 40
    assert report.candidates[2].stage_metrics.rerank_usage_missing_case_count == 0


def test_answer_failure_is_isolated_without_retry_and_keeps_reserved_budget() -> None:
    evaluation_set, corpus, categories = load_assets()
    answer = FailFirstAnswerAdapter()
    budget = EvaluationBudget(limits())

    report = run_evaluation(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        retrieval_port=FixedRetrievalAdapter(),
        answer_port=answer,
        report_version="failure_isolation_v1",
        run_kind="candidate_comparison",
        run_guard=budget,
    )

    assert answer.calls == 40
    assert report.metrics.failed_case_count == 1
    assert report.metrics.completed_case_count == 39
    assert report.cases[0].error_stage == "answer"
    assert budget.model_calls == 40
    assert budget.model_input_tokens == 9900 + 39 * 100
    assert budget.model_output_tokens == 2048 + 39 * 20
    budget.ensure_settled()
