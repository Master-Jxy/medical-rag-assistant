"""组装冻结基线与两个只读真实候选的最终对比报告。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean

from app.evaluation.budget import EvaluationBudget
from app.evaluation.candidate_adapters import CandidateRetrievalAdapter
from app.evaluation.comparison_schemas import (
    CandidateComparisonResult,
    CandidateProfile,
    CandidateStageMetrics,
    RagComparisonReport,
)
from app.evaluation.ports import EvaluationAnswerPort
from app.evaluation.report_schemas import BaselineReport
from app.evaluation.runner import calculate_evaluation_checksum, run_evaluation
from app.evaluation.schemas import CorpusManifest, EvaluationSet

EMBEDDING_TOKENS_RESERVED_PER_CALL = 512
EMBEDDING_PRICE_PER_MILLION_TOKENS_CNY = 0.5


@dataclass(frozen=True)
class RealCandidatePorts:
    profile: CandidateProfile
    retrieval: CandidateRetrievalAdapter
    answer: EvaluationAnswerPort


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _stage_metrics(
    *,
    profile: CandidateProfile,
    report: BaselineReport,
    retrieval: CandidateRetrievalAdapter | None,
    embedding_call_count: int,
) -> CandidateStageMetrics:
    observations = list(retrieval.rerank_observations.values()) if retrieval else []
    attempted = [item for item in observations if item.attempted]
    external = [item for item in observations if item.external_call]
    rerank_latencies = [
        item.latency_ms for item in attempted if item.latency_ms is not None
    ]
    reported_usage = [item.usage for item in external if item.usage is not None]
    missing_usage = len(external) - len(reported_usage)
    rerank_tokens = sum(item.input_tokens for item in reported_usage)
    rerank_costs = [
        item.estimated_cost_cny
        for item in reported_usage
        if item.estimated_cost_cny is not None
    ]
    rerank_cost_complete = missing_usage == 0 and len(rerank_costs) == len(
        reported_usage
    )
    embedding_tokens = embedding_call_count * EMBEDDING_TOKENS_RESERVED_PER_CALL
    embedding_cost = round(
        embedding_tokens
        * EMBEDDING_PRICE_PER_MILLION_TOKENS_CNY
        / 1_000_000,
        6,
    )
    rerank_cost = round(sum(rerank_costs), 6)
    total_latencies = [
        item.total_latency_ms
        for item in report.cases
        if item.total_latency_ms is not None
    ]
    return CandidateStageMetrics(
        retrieval_pipeline_observed_case_count=(
            report.metrics.retrieval_observed_case_count
        ),
        mean_retrieval_pipeline_latency_ms=(
            report.metrics.mean_retrieval_latency_ms
        ),
        rerank_attempted_case_count=len(attempted),
        rerank_external_call_count=len(external),
        rerank_succeeded_case_count=sum(item.succeeded for item in observations),
        rerank_fallback_case_count=sum(item.fallback_used for item in observations),
        rerank_observed_case_count=len(attempted),
        mean_rerank_latency_ms=_mean(rerank_latencies),
        rerank_usage_reported_case_count=len(reported_usage),
        rerank_usage_missing_case_count=missing_usage,
        rerank_input_tokens=rerank_tokens,
        rerank_estimated_cost_cny=rerank_cost,
        rerank_estimated_cost_complete=rerank_cost_complete,
        embedding_tokens_reserved=embedding_tokens,
        embedding_estimated_cost_cny=embedding_cost,
        answer_observed_case_count=report.metrics.answer_observed_case_count,
        mean_answer_latency_ms=report.metrics.mean_answer_latency_ms,
        mean_total_pipeline_latency_ms=_mean(total_latencies),
        total_tokens=(report.metrics.total_tokens + rerank_tokens + embedding_tokens),
        total_estimated_cost_cny=round(
            report.metrics.estimated_cost_cny + rerank_cost + embedding_cost,
            6,
        ),
        total_estimated_cost_complete=(
            report.metrics.estimated_cost_complete and rerank_cost_complete
        ),
    )


def build_real_comparison(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    baseline_profile: CandidateProfile,
    frozen_baseline: BaselineReport,
    new_candidates: list[RealCandidatePorts],
    budget: EvaluationBudget,
    generated_at: datetime | None = None,
) -> RagComparisonReport:
    timestamp = generated_at or datetime.now(timezone.utc)
    baseline_report = frozen_baseline.model_copy(
        update={
            "report_version": "vector_baseline_comparison_v1",
            "run_kind": "candidate_comparison",
        }
    )
    candidates = [
        CandidateComparisonResult(
            profile=baseline_profile,
            evaluation_report=baseline_report,
            stage_metrics=_stage_metrics(
                profile=baseline_profile,
                report=baseline_report,
                retrieval=None,
                embedding_call_count=baseline_report.metrics.retrieval_observed_case_count,
            ),
        )
    ]
    for candidate in new_candidates:
        retrieval_calls_before = budget.retrieval_calls
        report = run_evaluation(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=category_config,
            retrieval_port=candidate.retrieval,
            answer_port=candidate.answer,
            report_version=f"{candidate.profile.candidate_id}_real_v1",
            run_kind="candidate_comparison",
            generated_at=timestamp,
            run_guard=budget,
        )
        candidates.append(
            CandidateComparisonResult(
                profile=candidate.profile,
                evaluation_report=report,
                stage_metrics=_stage_metrics(
                    profile=candidate.profile,
                    report=report,
                    retrieval=candidate.retrieval,
                    embedding_call_count=(
                        budget.retrieval_calls - retrieval_calls_before
                    ),
                ),
            )
        )
    budget.ensure_settled()
    return RagComparisonReport(
        schema_version="rag_comparison_report_v1",
        report_version="rag_v1_2_real_comparison_v1",
        run_kind="real_comparison",
        generated_at=timestamp.astimezone(timezone.utc),
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=evaluation_set.corpus_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        candidates=candidates,
    )
