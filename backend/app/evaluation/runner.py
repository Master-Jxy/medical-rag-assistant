"""纯离线评估编排和确定性评分，不依赖线上 RAG 或会话服务。"""

import hashlib
import json
from datetime import datetime, timezone
from statistics import fmean

from app.evaluation.ports import (
    EvaluationAnswerPort,
    EvaluationQuery,
    EvaluationRetrievalPort,
    EvaluationRunGuard,
)
from app.evaluation.budget import EvaluationBudgetExceeded
from app.evaluation.report_schemas import (
    BaselineCaseResult,
    BaselineMetrics,
    BaselineReport,
    BaselineScoringMethods,
    BaselineTokenUsage,
)
from app.evaluation.schemas import CorpusManifest, EvaluationSet, ExpectedBehavior
from app.evaluation.validation import validate_evaluation_set


def calculate_evaluation_checksum(evaluation_set: EvaluationSet) -> str:
    canonical = json.dumps(
        evaluation_set.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _rate(correct: list[bool]) -> float | None:
    return round(sum(correct) / len(correct), 6) if correct else None


def run_evaluation(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    retrieval_port: EvaluationRetrievalPort,
    answer_port: EvaluationAnswerPort,
    report_version: str,
    run_kind: str,
    generated_at: datetime | None = None,
    run_guard: EvaluationRunGuard | None = None,
) -> BaselineReport:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    timestamp = generated_at or datetime.now(timezone.utc)
    results: list[BaselineCaseResult] = []

    for case in evaluation_set.cases:
        query = EvaluationQuery(
            case_id=case.case_id,
            question=case.question,
            history=tuple((turn.role, turn.content) for turn in case.history),
        )
        try:
            if run_guard is not None:
                run_guard.before_retrieval()
            retrieval = retrieval_port.retrieve(query)
            if retrieval.latency_ms < 0:
                raise ValueError("retrieval latency must be nonnegative")
        except EvaluationBudgetExceeded:
            raise
        except Exception as exc:
            results.append(
                BaselineCaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    expected_behavior=case.expected_behavior,
                    status="failed",
                    retrieved_source_document_ids=[],
                    actual_behavior=None,
                    source_recall=None,
                    source_full_hit=None,
                    behavior_correct=None,
                    expected_key_fact_count=len(case.expected_key_facts),
                    matched_key_fact_count=0,
                    key_fact_coverage=None,
                    retrieval_latency_ms=None,
                    answer_latency_ms=None,
                    total_latency_ms=None,
                    usage=None,
                    error_stage="retrieval",
                    error_type=type(exc).__name__,
                )
            )
            continue

        expected_sources = set(case.expected_source_document_ids)
        retrieved_sources = set(retrieval.source_document_ids)
        if expected_sources:
            source_recall = len(expected_sources & retrieved_sources) / len(
                expected_sources
            )
            source_full_hit = expected_sources.issubset(retrieved_sources)
        else:
            source_recall = None
            source_full_hit = None

        try:
            if run_guard is not None:
                run_guard.before_answer()
            answer = answer_port.answer(query, retrieval.source_document_ids)
            if answer.latency_ms < 0:
                raise ValueError("answer latency must be nonnegative")
            if run_guard is not None:
                run_guard.record_answer_usage(answer.usage)
        except EvaluationBudgetExceeded:
            raise
        except Exception as exc:
            if run_guard is not None:
                run_guard.record_answer_failure()
            results.append(
                BaselineCaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    expected_behavior=case.expected_behavior,
                    status="failed",
                    retrieved_source_document_ids=list(retrieval.source_document_ids),
                    actual_behavior=None,
                    source_recall=source_recall,
                    source_full_hit=source_full_hit,
                    behavior_correct=None,
                    expected_key_fact_count=len(case.expected_key_facts),
                    matched_key_fact_count=0,
                    key_fact_coverage=None,
                    retrieval_latency_ms=retrieval.latency_ms,
                    answer_latency_ms=None,
                    total_latency_ms=None,
                    usage=None,
                    error_stage="answer",
                    error_type=type(exc).__name__,
                )
            )
            continue

        normalized_answer = _normalized_text(answer.answer_text)
        matched_key_facts = sum(
            _normalized_text(fact) in normalized_answer
            for fact in case.expected_key_facts
        )
        key_fact_coverage = matched_key_facts / len(case.expected_key_facts)
        usage = None
        if answer.usage is not None:
            usage = BaselineTokenUsage(
                input_tokens=answer.usage.input_tokens,
                output_tokens=answer.usage.output_tokens,
                total_tokens=answer.usage.input_tokens + answer.usage.output_tokens,
                estimated_cost_cny=answer.usage.estimated_cost_cny,
            )
        results.append(
            BaselineCaseResult(
                case_id=case.case_id,
                category=case.category,
                expected_behavior=case.expected_behavior,
                status="completed",
                retrieved_source_document_ids=list(retrieval.source_document_ids),
                actual_behavior=answer.behavior,
                source_recall=source_recall,
                source_full_hit=source_full_hit,
                behavior_correct=answer.behavior == case.expected_behavior,
                expected_key_fact_count=len(case.expected_key_facts),
                matched_key_fact_count=matched_key_facts,
                key_fact_coverage=key_fact_coverage,
                retrieval_latency_ms=retrieval.latency_ms,
                answer_latency_ms=answer.latency_ms,
                total_latency_ms=retrieval.latency_ms + answer.latency_ms,
                usage=usage,
                error_stage=None,
                error_type=None,
            )
        )

    completed = [result for result in results if result.status == "completed"]
    failed = [result for result in results if result.status == "failed"]
    source_scored = [result for result in results if result.source_recall is not None]
    behavior_scored = [
        result.behavior_correct
        for result in completed
        if result.behavior_correct is not None
    ]
    refusal_scored = [
        result.behavior_correct
        for result in completed
        if result.expected_behavior == ExpectedBehavior.REFUSE
        and result.behavior_correct is not None
    ]
    key_fact_scored = [
        result.key_fact_coverage
        for result in completed
        if result.key_fact_coverage is not None
    ]
    retrieval_latencies = [
        result.retrieval_latency_ms
        for result in results
        if result.retrieval_latency_ms is not None
    ]
    answer_latencies = [
        result.answer_latency_ms
        for result in completed
        if result.answer_latency_ms is not None
    ]
    reported_usage = [result.usage for result in completed if result.usage is not None]
    missing_usage_count = sum(result.usage is None for result in completed)
    costs = [
        usage.estimated_cost_cny
        for usage in reported_usage
        if usage.estimated_cost_cny is not None
    ]
    cost_complete = (
        not failed
        and missing_usage_count == 0
        and len(costs) == len(reported_usage)
    )
    metrics = BaselineMetrics(
        case_count=len(results),
        completed_case_count=len(completed),
        failed_case_count=len(failed),
        source_scored_case_count=len(source_scored),
        mean_source_recall=_mean([result.source_recall for result in source_scored]),
        full_source_hit_rate=_rate(
            [result.source_full_hit for result in source_scored]
        ),
        behavior_scored_case_count=len(behavior_scored),
        behavior_accuracy=_rate(behavior_scored),
        refusal_scored_case_count=len(refusal_scored),
        refusal_accuracy=_rate(refusal_scored),
        key_fact_scored_case_count=len(key_fact_scored),
        mean_key_fact_coverage=_mean(key_fact_scored),
        retrieval_observed_case_count=len(retrieval_latencies),
        mean_retrieval_latency_ms=_mean(retrieval_latencies),
        answer_observed_case_count=len(answer_latencies),
        mean_answer_latency_ms=_mean(answer_latencies),
        usage_reported_case_count=len(reported_usage),
        usage_missing_case_count=missing_usage_count,
        total_input_tokens=sum(usage.input_tokens for usage in reported_usage),
        total_output_tokens=sum(usage.output_tokens for usage in reported_usage),
        total_tokens=sum(usage.total_tokens for usage in reported_usage),
        estimated_cost_cny=round(sum(costs), 6),
        estimated_cost_complete=cost_complete,
    )
    return BaselineReport(
        schema_version="baseline_report_v1",
        report_version=report_version,
        run_kind=run_kind,
        runner_version="baseline_runner_v1",
        generated_at=timestamp.astimezone(timezone.utc),
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=evaluation_set.corpus_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        retrieval_adapter=retrieval_port.adapter_name,
        answer_adapter=answer_port.adapter_name,
        scoring_methods=BaselineScoringMethods(
            source_recall="expected_document_id_recall_v1",
            behavior="expected_behavior_exact_match_v1",
            key_fact="normalized_exact_substring_v1",
        ),
        metrics=metrics,
        cases=results,
    )
