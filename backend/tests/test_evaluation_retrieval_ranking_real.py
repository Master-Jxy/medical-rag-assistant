from pathlib import Path

import pytest

from app.evaluation.budget import EvaluationBudget, EvaluationBudgetExceeded, EvaluationBudgetLimits
from app.evaluation.ports import EvaluationQuery
from app.evaluation.retrieval_ranking_adapters import SharedRetrievalRankingAdapter
from app.evaluation.retrieval_ranking_preflight import run_full_ranking_preflight
from app.evaluation.retrieval_ranking_real_schemas import RetrievalRankingRunPlan
from app.evaluation.retrieval_ranking_real import build_real_retrieval_ranking_report
from app.core.config import get_settings
from app.modules.rag.policies import HybridSearchPolicy
from app.modules.rag.adapters import CurrentChromaKnowledgeSearchAdapter
from app.modules.rag.ports import RerankResult, RerankUsage, RetrievedChunk
from scripts import run_real_retrieval_ranking as command
from scripts.run_mock_comparison import load_assets


def chunk(index: int, document_id: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        content=f"content-{index}", file_name=f"{index}.txt", page=1,
        chunk_id=f"chunk-{index}", document_id=document_id or f"doc-{index}",
    )


class Search:
    def __init__(self, results=None, error: Exception | None = None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, query, top_k, options=None):
        self.calls.append((query, top_k, options))
        if self.error:
            raise self.error
        return list(self.results)


class Reranker:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = []

    def rerank(self, query, candidates, top_n):
        self.calls.append((query, candidates, top_n))
        if self.error:
            raise self.error
        return RerankResult(
            chunks=list(reversed(candidates[:top_n])),
            usage=RerankUsage(request_count=1, input_tokens=120, estimated_cost_cny=0.000096),
        )


def budget(**overrides):
    values = dict(
        max_retrieval_calls=40, max_model_calls=1, max_total_tokens=1_220_480,
        max_estimated_cost_cny=1.1, embedding_tokens_reserved_per_call=512,
        model_input_tokens_reserved_per_call=1, model_output_tokens_reserved_per_call=1,
        embedding_price_per_million_tokens_cny=0.5,
        model_input_price_per_million_tokens_cny=0.000001,
        model_output_price_per_million_tokens_cny=0.000001,
        max_rerank_calls=40, rerank_tokens_reserved_per_call=30_000,
        rerank_cost_reserved_per_call_cny=0.024,
    )
    values.update(overrides)
    return EvaluationBudget(EvaluationBudgetLimits(**values))


def adapter(vector, keyword, reranker, active_budget=None):
    return SharedRetrievalRankingAdapter(
        vector_search=vector, keyword_search=keyword, reranker=reranker,
        budget=active_budget or budget(),
        hybrid_policy=HybridSearchPolicy(enabled=True, vector_weight=0.7, keyword_weight=0.3, rrf_k=60),
    )


def query():
    return EvaluationQuery("eval_001", "current", (("user", "previous"),))


def test_four_candidates_share_one_vector_and_one_keyword_call():
    vector = Search([chunk(i, f"doc-{(i - 1) // 2}") for i in range(1, 13)])
    keyword = Search([chunk(i) for i in range(12, 0, -1)])
    reranker = Reranker()
    result = adapter(vector, keyword, reranker).evaluate(query())
    assert len(vector.calls) == len(keyword.calls) == len(reranker.calls) == 1
    assert vector.calls[0][1] == keyword.calls[0][1] == 12
    assert reranker.calls[0][2] == 4
    assert set(result.candidates) == {
        "vector_top4_reference", "vector_wide_diverse_v1",
        "hybrid_wide_diverse_v1", "hybrid_wide_diverse_rerank_v1",
    }
    assert result.execution.rerank_succeeded is True


def test_keyword_failure_is_not_retried_and_hybrid_falls_back_to_vector():
    vector = Search([chunk(i) for i in range(1, 6)])
    keyword = Search(error=RuntimeError("offline"))
    result = adapter(vector, keyword, Reranker()).evaluate(query())
    assert len(keyword.calls) == 1
    assert result.execution.hybrid_fallback_used is True
    assert "keyword" in result.execution.error_stages
    assert result.candidates["hybrid_wide_diverse_v1"] == result.candidates["vector_wide_diverse_v1"]


def test_rerank_failure_is_not_retried_and_keeps_worst_case_reservation():
    active_budget = budget()
    reranker = Reranker(error=RuntimeError("timeout"))
    result = adapter(Search([chunk(i) for i in range(1, 6)]), Search([]), reranker, active_budget).evaluate(query())
    assert len(reranker.calls) == 1
    assert result.execution.rerank_fallback_used is True
    assert active_budget.rerank_tokens == 30_000
    active_budget.ensure_settled()


def test_budget_stops_before_second_external_calls():
    active_budget = budget(max_retrieval_calls=1)
    instance = adapter(Search([chunk(1)]), Search([]), Reranker(), active_budget)
    instance.evaluate(query())
    with pytest.raises(EvaluationBudgetExceeded, match="retrieval_call_limit"):
        instance.evaluate(EvaluationQuery("eval_002", "next", ()))


def test_execution_requires_phrase_plan_hash_and_non_existing_output(monkeypatch, tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")
    output = tmp_path / "report.json"
    monkeypatch.setattr(command, "PLAN_PATH", plan)
    monkeypatch.setattr(command, "OUTPUT_PATH", output)
    digest = command.plan_sha256()
    with pytest.raises(ValueError, match="confirmation phrase"):
        command.authorize_execution(execute=True, confirmation=None, supplied_sha256=digest)
    with pytest.raises(ValueError, match="does not match"):
        command.authorize_execution(execute=True, confirmation=command.CONFIRMATION, supplied_sha256="0" * 64)
    assert command.authorize_execution(execute=True, confirmation=command.CONFIRMATION, supplied_sha256=digest) == digest
    output.write_text("frozen", encoding="utf-8")
    with pytest.raises(FileExistsError):
        command.authorize_execution(execute=True, confirmation=command.CONFIRMATION, supplied_sha256=digest)


def test_execution_module_has_no_qwen_or_business_write_dependencies():
    source = Path(command.__file__).read_text(encoding="utf-8")
    for forbidden in ("CurrentQwenAnswerAdapter", "ChatTongyi", "conversation", "sqlalchemy", "Session"):
        assert forbidden not in source


def test_full_preflight_is_local_and_rejects_a_tampered_plan():
    evaluation_set, corpus, categories = load_assets()
    plan = RetrievalRankingRunPlan.model_validate_json(command.PLAN_PATH.read_text(encoding="utf-8"))
    report = run_full_ranking_preflight(
        plan=plan, evaluation_set=evaluation_set, corpus=corpus,
        category_config=categories, settings=get_settings(),
        evaluation_root=command.EVALUATION_ROOT,
        current_manifest_reader=lambda _: corpus,
        collection_count_reader=lambda _: 103,
    )
    assert report.remote_connectivity_checked is False
    assert report.max_answer_calls == 0
    changed = plan.model_copy(deep=True)
    changed.candidate_profiles[0].display_name = "tampered"
    with pytest.raises(ValueError, match="frozen plan contract"):
        run_full_ranking_preflight(
            plan=changed, evaluation_set=evaluation_set, corpus=corpus,
            category_config=categories, settings=get_settings(),
            evaluation_root=command.EVALUATION_ROOT,
            current_manifest_reader=lambda _: corpus,
            collection_count_reader=lambda _: 103,
        )


def test_fake_forty_case_real_report_has_no_answer_calls_or_body_fields():
    evaluation_set, _, _ = load_assets()
    active_budget = budget()
    instance = adapter(
        Search([chunk(i) for i in range(1, 13)]),
        Search([chunk(i) for i in range(12, 0, -1)]),
        Reranker(),
        active_budget,
    )
    report = build_real_retrieval_ranking_report(
        evaluation_set=evaluation_set,
        adapter=instance,
        budget=active_budget,
        plan_sha256="0" * 64,
    )
    assert report.usage.embedding_calls == 40
    assert report.usage.keyword_scans == 40
    assert report.usage.rerank_calls == 40
    assert report.usage.answer_calls == 0
    payload = report.model_dump_json()
    for forbidden in ('"question"', '"answer_text"', '"content"', '"prompt"'):
        assert forbidden not in payload.lower()


def test_real_factory_wraps_similarity_search_store_in_knowledge_search_port(monkeypatch):
    class Store:
        def has_documents(self):
            return True

        def similarity_search(self, query, top_k, metadata_filter=None):
            return []

        def list_documents(self, metadata_filter=None):
            return []

    plan = RetrievalRankingRunPlan.model_validate_json(command.PLAN_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(command, "create_current_vector_search", lambda settings: Store())
    monkeypatch.setattr(command, "DashScopeRerankAdapter", lambda **kwargs: Reranker())
    instance = command.create_real_adapter(get_settings(), plan, budget())
    assert isinstance(instance._vector_search, CurrentChromaKnowledgeSearchAdapter)


def test_all_vector_failures_cannot_publish_a_formal_report():
    evaluation_set, _, _ = load_assets()
    active_budget = budget()
    instance = adapter(
        Search(error=AttributeError("missing search port")),
        Search([chunk(i) for i in range(1, 13)]),
        Reranker(),
        active_budget,
    )
    with pytest.raises(RuntimeError, match="all vector retrieval cases failed"):
        build_real_retrieval_ranking_report(
            evaluation_set=evaluation_set,
            adapter=instance,
            budget=active_budget,
            plan_sha256="0" * 64,
        )
