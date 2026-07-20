"""Orchestration for a real, retrieval-only ranking run."""

from datetime import datetime, timezone

from app.evaluation.budget import EvaluationBudget
from app.evaluation.ports import EvaluationQuery
from app.evaluation.retrieval_ranking import (
    aggregate_retrieval_ranking_cases,
    build_retrieval_ranking_profiles,
    calculate_retrieval_ranking_metrics,
)
from app.evaluation.retrieval_ranking_adapters import SharedRetrievalRankingAdapter
from app.evaluation.retrieval_ranking_real_schemas import (
    RankingUsageMetrics,
    RealRetrievalRankingReport,
)
from app.evaluation.retrieval_ranking_schemas import (
    RetrievalRankingCandidateResult,
    RetrievalRankingCaseResult,
    RetrievalRankingCategoryMetrics,
)
from app.evaluation.runner import calculate_evaluation_checksum
from app.evaluation.schemas import EvaluationCategory, EvaluationSet


def build_real_retrieval_ranking_report(
    *,
    evaluation_set: EvaluationSet,
    adapter: SharedRetrievalRankingAdapter,
    budget: EvaluationBudget,
    plan_sha256: str,
) -> RealRetrievalRankingReport:
    profiles = build_retrieval_ranking_profiles()
    cases_by_candidate: dict[str, list[RetrievalRankingCaseResult]] = {
        profile.candidate_id: [] for profile in profiles
    }
    executions = []
    for case in evaluation_set.cases:
        result = adapter.evaluate(
            EvaluationQuery(
                case_id=case.case_id,
                question=case.question,
                history=tuple((turn.role, turn.content) for turn in case.history),
            )
        )
        executions.append(result.execution)
        for profile in profiles:
            selection = result.candidates[profile.candidate_id]
            metrics, ranked_ids, final_ids = calculate_retrieval_ranking_metrics(
                expected_source_document_ids=case.expected_source_document_ids,
                ranked_candidates=selection.ranked_candidates,
                final_chunks=selection.final_chunks,
            )
            cases_by_candidate[profile.candidate_id].append(
                RetrievalRankingCaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    expected_source_document_ids=case.expected_source_document_ids,
                    ranked_document_ids_at_10=ranked_ids,
                    final_chunk_document_ids=final_ids,
                    metrics=metrics,
                )
            )
    if not any(item.vector_succeeded for item in executions):
        raise RuntimeError(
            "all vector retrieval cases failed; refusing to publish a ranking report"
        )
    budget.ensure_settled()
    candidates = []
    for profile in profiles:
        cases = cases_by_candidate[profile.candidate_id]
        category_metrics = [
            RetrievalRankingCategoryMetrics(
                category=category,
                **aggregate_retrieval_ranking_cases(
                    [item for item in cases if item.category == category]
                ).model_dump(),
            )
            for category in EvaluationCategory
        ]
        candidates.append(
            RetrievalRankingCandidateResult(
                profile=profile,
                metrics=aggregate_retrieval_ranking_cases(cases),
                category_metrics=category_metrics,
                cases=cases,
            )
        )
    return RealRetrievalRankingReport(
        schema_version="retrieval_ranking_real_report_v1",
        report_version="retrieval_ranking_real_v1",
        run_kind="real_retrieval_ranking",
        generated_at=datetime.now(timezone.utc),
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=evaluation_set.corpus_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        plan_sha256=plan_sha256,
        usage=RankingUsageMetrics(
            embedding_calls=budget.retrieval_calls,
            keyword_scans=adapter.keyword_scans,
            rerank_calls=budget.rerank_calls,
            answer_calls=0,
            embedding_tokens_reserved=budget.embedding_tokens,
            rerank_input_tokens=budget.rerank_tokens,
            estimated_cost_cny=round(budget.estimated_cost_cny, 6),
        ),
        case_executions=executions,
        candidates=candidates,
    )
