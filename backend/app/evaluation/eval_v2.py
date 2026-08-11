"""Stage 26.4 的无费用 eval_v2 运行器与候选晋级门禁。

这个模块只依赖评估 Port 和固定 fixture。它不会创建供应商客户端，也不会读取
生产 Chroma/MySQL，更不会把占位内容当成医学黄金答案。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean
from typing import Literal, Protocol

from pydantic import Field

from app.evaluation.corpus_v2 import (
    CorpusV2Manifest,
    CorpusV2PreflightReport,
    EvaluationCaseV2,
    EvaluationSetV2,
    preflight_corpus_v2,
)
from app.evaluation.schemas import StrictModel


class EvalV2CandidatePolicy(StrictModel):
    """候选池、文档配额和最终上下文是三个独立概念。"""

    candidate_pool_size: Literal[16] = 16
    max_chunks_per_document: Literal[2] = 2
    final_top_k: Literal[4] = 4
    retrieval_mode: Literal["vector", "hybrid_rrf"] = "vector"
    reranker_enabled: bool = False


class EvalV2ProviderCalls(StrictModel):
    embedding_calls: int = Field(default=0, ge=0)
    rerank_calls: int = Field(default=0, ge=0)
    qwen_calls: int = Field(default=0, ge=0)
    ocr_calls: int = Field(default=0, ge=0)
    vision_calls: int = Field(default=0, ge=0)


class EvalV2RetrievalObservation(StrictModel):
    ranked_document_ids: list[str]
    structured_evidence: list[str] = Field(default_factory=list)
    version_safe: bool = True
    latency_ms: float = Field(default=0, ge=0)


class EvalV2AnswerObservation(StrictModel):
    behavior: Literal["answer", "refuse"]
    answer_text: str = ""
    cited_source_document_ids: list[str] = Field(default_factory=list)
    structured_facts: dict[str, list[str]] = Field(default_factory=dict)
    structured_evidence: list[str] = Field(default_factory=list)
    version_safe: bool = True
    latency_ms: float = Field(default=0, ge=0)


class EvalV2Rubric(StrictModel):
    case_id: str
    expected_behavior: Literal["answer", "refuse", "blocked"]
    required_source_document_ids: list[str]
    rule_ids: list[str]
    accepted_fact_aliases: dict[str, list[str]]
    required_evidence: list[str]


class EvalV2CaseResult(StrictModel):
    case_id: str
    category: str
    status: Literal["completed", "blocked", "failed", "not_eligible"]
    expected_behavior: str
    actual_behavior: str | None = None
    retrieved_source_document_ids: list[str] = Field(default_factory=list)
    cited_source_document_ids: list[str] = Field(default_factory=list)
    source_recall_at_4: float | None = Field(default=None, ge=0, le=1)
    full_source_hit_at_4: bool | None = None
    mrr_at_4: float | None = Field(default=None, ge=0, le=1)
    ndcg_at_4: float | None = Field(default=None, ge=0, le=1)
    citation_valid: bool | None = None
    refusal_correct: bool | None = None
    fact_coverage: float | None = Field(default=None, ge=0, le=1)
    structured_requirement_passed: bool | None = None
    version_safe: bool | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    failure_code: str | None = None


class EvalV2Metrics(StrictModel):
    case_count: int = Field(ge=0)
    completed_case_count: int = Field(ge=0)
    blocked_case_count: int = Field(ge=0)
    failed_case_count: int = Field(ge=0)
    not_eligible_case_count: int = Field(ge=0)
    source_scored_case_count: int = Field(ge=0)
    mean_source_recall_at_4: float | None = Field(default=None, ge=0, le=1)
    full_source_hit_rate_at_4: float | None = Field(default=None, ge=0, le=1)
    mean_mrr_at_4: float | None = Field(default=None, ge=0, le=1)
    mean_ndcg_at_4: float | None = Field(default=None, ge=0, le=1)
    citation_scored_case_count: int = Field(ge=0)
    citation_accuracy: float | None = Field(default=None, ge=0, le=1)
    refusal_scored_case_count: int = Field(ge=0)
    refusal_accuracy: float | None = Field(default=None, ge=0, le=1)
    fact_scored_case_count: int = Field(ge=0)
    mean_fact_coverage: float | None = Field(default=None, ge=0, le=1)
    structured_scored_case_count: int = Field(ge=0)
    structured_accuracy: float | None = Field(default=None, ge=0, le=1)
    version_scored_case_count: int = Field(ge=0)
    version_safety_accuracy: float | None = Field(default=None, ge=0, le=1)
    mean_latency_ms: float | None = Field(default=None, ge=0)


class EvalV2MetricDiff(StrictModel):
    metric: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    passed: bool


class EvalV2PromotionReport(StrictModel):
    decision: Literal["promote", "hold", "not_eligible"]
    baseline_candidate_id: str | None = None
    candidate_id: str
    thresholds: dict[str, float]
    diffs: list[EvalV2MetricDiff]
    reasons: list[str]


class EvalV2Report(StrictModel):
    schema_version: Literal["eval_v2_report_v1"]
    report_version: str
    run_kind: Literal["fake_no_cost"]
    generated_at: datetime
    corpus_version: str
    corpus_checksum: str
    dataset_version: str
    candidate_id: str
    candidate_policy: EvalV2CandidatePolicy
    preflight: CorpusV2PreflightReport
    no_cost_gate_passed: bool
    provider_calls: EvalV2ProviderCalls
    metrics: EvalV2Metrics
    cases: list[EvalV2CaseResult]
    promotion: EvalV2PromotionReport


@dataclass(frozen=True, slots=True)
class _Retrieval:
    ranked_document_ids: tuple[str, ...]
    structured_evidence: frozenset[str]
    version_safe: bool
    latency_ms: float


@dataclass(frozen=True, slots=True)
class _Answer:
    behavior: str
    answer_text: str
    cited_source_document_ids: tuple[str, ...]
    structured_facts: dict[str, tuple[str, ...]]
    structured_evidence: frozenset[str]
    version_safe: bool
    latency_ms: float


class EvalV2RetrievalPort(Protocol):
    adapter_name: str

    def retrieve(self, case: EvaluationCaseV2) -> EvalV2RetrievalObservation: ...


class EvalV2AnswerPort(Protocol):
    adapter_name: str

    def answer(
        self,
        case: EvaluationCaseV2,
        retrieved_document_ids: tuple[str, ...],
    ) -> EvalV2AnswerObservation: ...


class FakeEvalV2RetrievalAdapter:
    """只返回评估契约中的文档 ID，不生成任何医学正文。"""

    adapter_name = "fake_eval_v2_retrieval_v1"

    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, case: EvaluationCaseV2) -> EvalV2RetrievalObservation:
        self.calls += 1
        evidence = {
            "table" if case.category == "table" else "",
            "ocr" if case.category == "scan_ocr" else "",
            "vision" if case.category == "image_vision" else "",
        }
        ranked = list(case.expected_source_document_ids)
        if ranked:
            ranked.append(ranked[0])
        return EvalV2RetrievalObservation(
            ranked_document_ids=ranked,
            structured_evidence=sorted(item for item in evidence if item),
            version_safe=case.category != "version_conflict",
            latency_ms=1.0,
        )


class FakeEvalV2AnswerAdapter:
    """用 rubric 的同义词和结构化键模拟结果，仍不包含医学黄金正文。"""

    adapter_name = "fake_eval_v2_answer_v1"

    def __init__(self) -> None:
        self.calls = 0

    def answer(
        self,
        case: EvaluationCaseV2,
        retrieved_document_ids: tuple[str, ...],
    ) -> EvalV2AnswerObservation:
        self.calls += 1
        aliases = case.accepted_fact_aliases
        answer_text = " ".join(
            alias
            for values in aliases.values()
            for alias in values[:1]
        )
        structured_evidence = {
            "table" if case.category == "table" else "",
            "ocr" if case.category == "scan_ocr" else "",
            "vision" if case.category == "image_vision" else "",
        }
        return EvalV2AnswerObservation(
            behavior="refuse" if case.expected_behavior == "refuse" else "answer",
            answer_text=answer_text,
            cited_source_document_ids=list(retrieved_document_ids),
            structured_facts={key: values[:1] for key, values in aliases.items()},
            structured_evidence=sorted(item for item in structured_evidence if item),
            version_safe=case.category != "version_conflict",
            latency_ms=1.0,
        )


def build_structured_rubric(case: EvaluationCaseV2) -> EvalV2Rubric:
    required_evidence: list[str] = []
    if case.category == "table":
        required_evidence.append("table")
    elif case.category == "scan_ocr":
        required_evidence.append("ocr")
    elif case.category == "image_vision":
        required_evidence.append("vision")
    elif case.category == "version_conflict":
        required_evidence.append("version_safe")
    return EvalV2Rubric(
        case_id=case.case_id,
        expected_behavior=case.expected_behavior,
        required_source_document_ids=list(case.expected_source_document_ids),
        rule_ids=list(case.scoring_rules),
        accepted_fact_aliases={
            key: list(values) for key, values in case.accepted_fact_aliases.items()
        },
        required_evidence=required_evidence,
    )


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _coerce_retrieval(value: object) -> _Retrieval:
    ranked = tuple(
        str(item)
        for item in getattr(value, "ranked_document_ids", getattr(value, "source_document_ids", ()))
    )
    return _Retrieval(
        ranked_document_ids=ranked,
        structured_evidence=frozenset(str(item) for item in getattr(value, "structured_evidence", ())),
        version_safe=bool(getattr(value, "version_safe", True)),
        latency_ms=float(getattr(value, "latency_ms", 0.0)),
    )


def _coerce_answer(value: object) -> _Answer:
    facts = {
        str(key): tuple(str(item) for item in values)
        for key, values in getattr(value, "structured_facts", {}).items()
    }
    return _Answer(
        behavior=str(getattr(value, "behavior")),
        answer_text=str(getattr(value, "answer_text", "")),
        cited_source_document_ids=tuple(
            str(item) for item in getattr(value, "cited_source_document_ids", ())
        ),
        structured_facts=facts,
        structured_evidence=frozenset(str(item) for item in getattr(value, "structured_evidence", ())),
        version_safe=bool(getattr(value, "version_safe", True)),
        latency_ms=float(getattr(value, "latency_ms", 0.0)),
    )


def _select_documents(
    ranked: tuple[str, ...],
    policy: EvalV2CandidatePolicy,
) -> tuple[str, ...]:
    bounded = ranked[: policy.candidate_pool_size]
    counts: dict[str, int] = {}
    selected: list[str] = []
    for document_id in bounded:
        counts[document_id] = counts.get(document_id, 0)
        if counts[document_id] >= policy.max_chunks_per_document:
            continue
        counts[document_id] += 1
        selected.append(document_id)
    return tuple(selected[: policy.final_top_k])


def _ranking_metrics(expected: list[str], final_documents: tuple[str, ...]) -> tuple[float | None, bool | None, float | None, float | None]:
    if not expected:
        return None, None, None, None
    unique: list[str] = []
    for item in final_documents:
        if item not in unique:
            unique.append(item)
    expected_set = set(expected)
    recall = len(expected_set.intersection(unique)) / len(expected_set)
    full = expected_set.issubset(unique)
    first = next((index for index, item in enumerate(unique, start=1) if item in expected_set), None)
    mrr = 0.0 if first is None else 1 / first
    dcg = sum(
        1 / math.log2(index + 1)
        for index, item in enumerate(unique, start=1)
        if item in expected_set
    )
    ideal = sum(1 / math.log2(index + 1) for index in range(1, min(len(expected_set), 4) + 1))
    return round(recall, 6), full, round(mrr, 6), round(dcg / ideal, 6) if ideal else 0.0


def _fact_coverage(case: EvaluationCaseV2, answer: _Answer) -> float | None:
    if not case.accepted_fact_aliases:
        return None
    answer_text = _normalise(answer.answer_text)
    structured_values = {
        _normalise(value)
        for values in answer.structured_facts.values()
        for value in values
    }
    matched = 0
    for canonical, aliases in case.accepted_fact_aliases.items():
        candidates = {_normalise(canonical), *(_normalise(alias) for alias in aliases)}
        if any(candidate and (candidate in answer_text or candidate in structured_values) for candidate in candidates):
            matched += 1
    return round(matched / len(case.accepted_fact_aliases), 6)


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def _metric_diff(metric: str, baseline: float | None, candidate: float | None, *, minimum: float = 0.0) -> EvalV2MetricDiff:
    delta = None if baseline is None or candidate is None else round(candidate - baseline, 6)
    return EvalV2MetricDiff(
        metric=metric,
        baseline=baseline,
        candidate=candidate,
        delta=delta,
        passed=delta is not None and delta >= minimum,
    )


def build_promotion_report(
    *,
    baseline: EvalV2Report,
    candidate: EvalV2Report,
) -> EvalV2PromotionReport:
    thresholds = {
        "overall_source_recall_delta_min": 0.0,
        "multi_source_recall_delta_min": 0.05,
        "overall_full_source_hit_delta_min": 0.03,
        "behavior_accuracy_delta_min": 0.0,
        "refusal_accuracy_delta_min": 0.0,
        "citation_accuracy_delta_min": 0.0,
    }
    if baseline.preflight.status != "eligible" or candidate.preflight.status != "eligible":
        return EvalV2PromotionReport(
            decision="not_eligible",
            baseline_candidate_id=baseline.candidate_id,
            candidate_id=candidate.candidate_id,
            thresholds=thresholds,
            diffs=[],
            reasons=["baseline 或 candidate 没有通过 corpus_v2 人工黄金资料与合法性门禁"],
        )
    diffs = [
        _metric_diff(
            "mean_source_recall_at_4",
            baseline.metrics.mean_source_recall_at_4,
            candidate.metrics.mean_source_recall_at_4,
        ),
        _metric_diff(
            "full_source_hit_rate_at_4",
            baseline.metrics.full_source_hit_rate_at_4,
            candidate.metrics.full_source_hit_rate_at_4,
        ),
        _metric_diff(
            "citation_accuracy",
            baseline.metrics.citation_accuracy,
            candidate.metrics.citation_accuracy,
        ),
        _metric_diff(
            "refusal_accuracy",
            baseline.metrics.refusal_accuracy,
            candidate.metrics.refusal_accuracy,
        ),
    ]
    multi_baseline = baseline.metrics.mean_source_recall_at_4
    multi_candidate = candidate.metrics.mean_source_recall_at_4
    multi_diff = _metric_diff(
        "multi_source_recall_at_4",
        multi_baseline,
        multi_candidate,
        minimum=thresholds["multi_source_recall_delta_min"],
    )
    diffs.append(multi_diff)
    reasons: list[str] = []
    overall = diffs[0]
    full = diffs[1]
    citations = diffs[2]
    refusal = diffs[3]
    multi_gain = multi_diff.passed
    full_gain = full.delta is not None and full.delta >= thresholds["overall_full_source_hit_delta_min"]
    if not overall.passed:
        reasons.append("总体 source_recall_at_4 不能低于冻结基线")
    if not (multi_gain or full_gain):
        reasons.append("多文档召回至少提升0.05，或总体完整命中率至少提升0.03")
    if not citations.passed:
        reasons.append("引用准确率不能回退")
    if not refusal.passed:
        reasons.append("拒答准确率不能回退")
    if candidate.candidate_policy.retrieval_mode == "vector" and not candidate.candidate_policy.reranker_enabled:
        reasons.append("冻结向量基线不需要晋级")
    decision: Literal["promote", "hold", "not_eligible"] = "promote" if not reasons else "hold"
    return EvalV2PromotionReport(
        decision=decision,
        baseline_candidate_id=baseline.candidate_id,
        candidate_id=candidate.candidate_id,
        thresholds=thresholds,
        diffs=diffs,
        reasons=reasons or ["候选超过冻结基线门槛，可进入独立发布评审"],
    )


def run_eval_v2(
    *,
    manifest: CorpusV2Manifest,
    evaluation_set: EvaluationSetV2,
    asset_root,
    retrieval_port: EvalV2RetrievalPort | None = None,
    answer_port: EvalV2AnswerPort | None = None,
    candidate_id: str = "vector_baseline_v2",
    candidate_policy: EvalV2CandidatePolicy | None = None,
    baseline_report: EvalV2Report | None = None,
    generated_at: datetime | None = None,
) -> EvalV2Report:
    """运行无费用 eval_v2；当前资产不合格时不调用任何适配器。"""

    policy = candidate_policy or EvalV2CandidatePolicy()
    preflight = preflight_corpus_v2(manifest, evaluation_set, asset_root=asset_root)
    provider_calls = EvalV2ProviderCalls()
    cases: list[EvalV2CaseResult] = []
    if preflight.eligible:
        retrieval_port = retrieval_port or FakeEvalV2RetrievalAdapter()
        answer_port = answer_port or FakeEvalV2AnswerAdapter()
        for case in evaluation_set.cases:
            if case.expected_behavior == "blocked":
                cases.append(
                    EvalV2CaseResult(
                        case_id=case.case_id,
                        category=case.category,
                        status="blocked",
                        expected_behavior=case.expected_behavior,
                    )
                )
                continue
            try:
                retrieval = _coerce_retrieval(retrieval_port.retrieve(case))
                final_documents = _select_documents(retrieval.ranked_document_ids, policy)
                answer = _coerce_answer(answer_port.answer(case, final_documents))
                recall, full_hit, mrr, ndcg = _ranking_metrics(
                    case.expected_source_document_ids,
                    final_documents,
                )
                cited = list(answer.cited_source_document_ids)
                citation_valid = (
                    set(cited).issubset(set(final_documents))
                    and set(case.expected_source_document_ids).issubset(set(cited))
                    if case.expected_source_document_ids
                    else not cited
                )
                required_evidence = set(build_structured_rubric(case).required_evidence)
                observed_evidence = retrieval.structured_evidence | answer.structured_evidence
                structured_passed = (
                    required_evidence.issubset(observed_evidence)
                    if required_evidence
                    else None
                )
                version_safe = retrieval.version_safe and answer.version_safe
                if case.category == "version_conflict":
                    structured_passed = bool(structured_passed) and version_safe
                cases.append(
                    EvalV2CaseResult(
                        case_id=case.case_id,
                        category=case.category,
                        status="completed",
                        expected_behavior=case.expected_behavior,
                        actual_behavior=answer.behavior,
                        retrieved_source_document_ids=list(final_documents),
                        cited_source_document_ids=cited,
                        source_recall_at_4=recall,
                        full_source_hit_at_4=full_hit,
                        mrr_at_4=mrr,
                        ndcg_at_4=ndcg,
                        citation_valid=citation_valid,
                        refusal_correct=(answer.behavior == case.expected_behavior),
                        fact_coverage=_fact_coverage(case, answer),
                        structured_requirement_passed=structured_passed,
                        version_safe=version_safe,
                        latency_ms=round(retrieval.latency_ms + answer.latency_ms, 6),
                    )
                )
            except Exception as exc:
                cases.append(
                    EvalV2CaseResult(
                        case_id=case.case_id,
                        category=case.category,
                        status="failed",
                        expected_behavior=case.expected_behavior,
                        failure_code=type(exc).__name__,
                    )
                )
    else:
        cases = [
            EvalV2CaseResult(
                case_id=case.case_id,
                category=case.category,
                status="blocked" if case.expected_behavior == "blocked" else "not_eligible",
                expected_behavior=case.expected_behavior,
            )
            for case in evaluation_set.cases
        ]

    completed = [item for item in cases if item.status == "completed"]
    scored_sources = [item for item in completed if item.source_recall_at_4 is not None]
    citation_scored = [item for item in completed if item.citation_valid is not None]
    refusal_scored = [item for item in completed if item.refusal_correct is not None]
    fact_scored = [item for item in completed if item.fact_coverage is not None]
    structured_scored = [item for item in completed if item.structured_requirement_passed is not None]
    version_scored = [item for item in completed if item.category == "version_conflict" and item.version_safe is not None]
    metrics = EvalV2Metrics(
        case_count=len(cases),
        completed_case_count=len(completed),
        blocked_case_count=sum(item.status == "blocked" for item in cases),
        failed_case_count=sum(item.status == "failed" for item in cases),
        not_eligible_case_count=sum(item.status == "not_eligible" for item in cases),
        source_scored_case_count=len(scored_sources),
        mean_source_recall_at_4=_mean([item.source_recall_at_4 for item in scored_sources if item.source_recall_at_4 is not None]),
        full_source_hit_rate_at_4=_mean([float(item.full_source_hit_at_4) for item in scored_sources if item.full_source_hit_at_4 is not None]),
        mean_mrr_at_4=_mean([item.mrr_at_4 for item in scored_sources if item.mrr_at_4 is not None]),
        mean_ndcg_at_4=_mean([item.ndcg_at_4 for item in scored_sources if item.ndcg_at_4 is not None]),
        citation_scored_case_count=len(citation_scored),
        citation_accuracy=_mean([float(item.citation_valid) for item in citation_scored]),
        refusal_scored_case_count=len(refusal_scored),
        refusal_accuracy=_mean([float(item.refusal_correct) for item in refusal_scored]),
        fact_scored_case_count=len(fact_scored),
        mean_fact_coverage=_mean([item.fact_coverage for item in fact_scored if item.fact_coverage is not None]),
        structured_scored_case_count=len(structured_scored),
        structured_accuracy=_mean([float(item.structured_requirement_passed) for item in structured_scored]),
        version_scored_case_count=len(version_scored),
        version_safety_accuracy=_mean([float(item.version_safe) for item in version_scored if item.version_safe is not None]),
        mean_latency_ms=_mean([item.latency_ms for item in completed if item.latency_ms is not None]),
    )
    if baseline_report is None:
        promotion = EvalV2PromotionReport(
            decision="not_eligible",
            candidate_id=candidate_id,
            thresholds={},
            diffs=[],
            reasons=["未提供冻结基线，候选不能直接晋级"],
        )
    else:
        provisional = EvalV2Report(
            schema_version="eval_v2_report_v1",
            report_version="eval_v2_provisional_v1",
            run_kind="fake_no_cost",
            generated_at=generated_at or datetime.now(timezone.utc),
            corpus_version=manifest.corpus_version,
            corpus_checksum=manifest.corpus_checksum,
            dataset_version=evaluation_set.dataset_version,
            candidate_id=candidate_id,
            candidate_policy=policy,
            preflight=preflight,
            no_cost_gate_passed=True,
            provider_calls=provider_calls,
            metrics=metrics,
            cases=cases,
            promotion=EvalV2PromotionReport(
                decision="not_eligible",
                candidate_id=candidate_id,
                thresholds={},
                diffs=[],
                reasons=["provisional"],
            ),
        )
        promotion = build_promotion_report(baseline=baseline_report, candidate=provisional)
    actual_report = EvalV2Report(
        schema_version="eval_v2_report_v1",
        report_version="eval_v2_fake_no_cost_v1",
        run_kind="fake_no_cost",
        generated_at=generated_at or datetime.now(timezone.utc),
        corpus_version=manifest.corpus_version,
        corpus_checksum=manifest.corpus_checksum,
        dataset_version=evaluation_set.dataset_version,
        candidate_id=candidate_id,
        candidate_policy=policy,
        preflight=preflight,
        no_cost_gate_passed=not any(provider_calls.model_dump().values()),
        provider_calls=provider_calls,
        metrics=metrics,
        cases=cases,
        promotion=promotion,
    )
    return actual_report


run_fake_eval_v2 = run_eval_v2
