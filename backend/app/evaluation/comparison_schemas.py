"""RAG候选方案对比报告与受控运行计划的数据契约。"""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.evaluation.report_schemas import BaselineReport
from app.evaluation.schemas import StrictModel


class CandidateRetrievalConfiguration(StrictModel):
    query_builder_version: str
    vector_adapter: str
    embedding_model: str
    chroma_collection: str
    top_k: Literal[4]
    minimum_relevance_score: float | None = Field(default=None, ge=0, le=1)
    metadata_filters: dict[str, str]
    hybrid_enabled: bool
    keyword_adapter: str
    vector_weight: float = Field(ge=0, le=1)
    keyword_weight: float = Field(ge=0, le=1)
    rrf_k: int = Field(ge=1, le=1000)


class CandidateRerankConfiguration(StrictModel):
    enabled: bool
    adapter: str
    model: str
    max_candidates: int = Field(ge=1, le=100)
    timeout_seconds: float = Field(gt=0, le=30)
    max_input_tokens: int = Field(ge=1, le=120000)
    input_price_per_million_tokens_cny: float = Field(ge=0)
    max_estimated_cost_cny: float = Field(ge=0)


class CandidateAnswerConfiguration(StrictModel):
    adapter: str
    model: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_output_tokens: int = Field(gt=0)


class CandidateTechnicalConfiguration(StrictModel):
    profile_version: Literal["rag_candidate_profile_v1"]
    retrieval: CandidateRetrievalConfiguration
    rerank: CandidateRerankConfiguration
    answer: CandidateAnswerConfiguration


def calculate_configuration_fingerprint(
    configuration: CandidateTechnicalConfiguration,
) -> str:
    canonical = json.dumps(
        configuration.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CandidateProfile(StrictModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9_]+_v[0-9]+$")
    display_name: str = Field(min_length=1, max_length=100)
    configuration: CandidateTechnicalConfiguration
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def fingerprint_matches_configuration(self) -> "CandidateProfile":
        expected = calculate_configuration_fingerprint(self.configuration)
        if self.configuration_fingerprint != expected:
            raise ValueError("候选方案配置指纹与完整配置不一致")
        return self


class CandidateStageMetrics(StrictModel):
    retrieval_pipeline_observed_case_count: int = Field(ge=0)
    mean_retrieval_pipeline_latency_ms: float | None = Field(default=None, ge=0)
    rerank_attempted_case_count: int = Field(ge=0)
    rerank_external_call_count: int = Field(ge=0)
    rerank_succeeded_case_count: int = Field(ge=0)
    rerank_fallback_case_count: int = Field(ge=0)
    rerank_observed_case_count: int = Field(ge=0)
    mean_rerank_latency_ms: float | None = Field(default=None, ge=0)
    rerank_usage_reported_case_count: int = Field(ge=0)
    rerank_usage_missing_case_count: int = Field(ge=0)
    rerank_input_tokens: int = Field(ge=0)
    rerank_estimated_cost_cny: float = Field(ge=0)
    rerank_estimated_cost_complete: bool
    embedding_tokens_reserved: int = Field(ge=0)
    embedding_estimated_cost_cny: float = Field(ge=0)
    answer_observed_case_count: int = Field(ge=0)
    mean_answer_latency_ms: float | None = Field(default=None, ge=0)
    mean_total_pipeline_latency_ms: float | None = Field(default=None, ge=0)
    total_tokens: int = Field(ge=0)
    total_estimated_cost_cny: float = Field(ge=0)
    total_estimated_cost_complete: bool

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "CandidateStageMetrics":
        if self.rerank_succeeded_case_count + self.rerank_fallback_case_count > self.rerank_attempted_case_count:
            raise ValueError("重排成功数与回退数不能超过尝试数")
        if self.rerank_external_call_count != (
            self.rerank_usage_reported_case_count
            + self.rerank_usage_missing_case_count
        ):
            raise ValueError("重排外部调用数必须等于有计量与缺失计量之和")
        return self


class CandidateComparisonResult(StrictModel):
    profile: CandidateProfile
    evaluation_report: BaselineReport
    stage_metrics: CandidateStageMetrics

    @model_validator(mode="after")
    def profile_matches_stage_metrics(self) -> "CandidateComparisonResult":
        if self.evaluation_report.run_kind != "candidate_comparison":
            raise ValueError("候选方案必须使用candidate_comparison运行类型")
        report_metrics = self.evaluation_report.metrics
        stage = self.stage_metrics
        if (
            stage.retrieval_pipeline_observed_case_count
            != report_metrics.retrieval_observed_case_count
            or stage.mean_retrieval_pipeline_latency_ms
            != report_metrics.mean_retrieval_latency_ms
            or stage.answer_observed_case_count
            != report_metrics.answer_observed_case_count
            or stage.mean_answer_latency_ms != report_metrics.mean_answer_latency_ms
        ):
            raise ValueError("分阶段耗时与评估报告不一致")
        if stage.total_tokens != (
            report_metrics.total_tokens
            + stage.rerank_input_tokens
            + stage.embedding_tokens_reserved
        ):
            raise ValueError("候选方案总Token与回答、重排计量不一致")
        expected_cost = round(
            report_metrics.estimated_cost_cny
            + stage.rerank_estimated_cost_cny
            + stage.embedding_estimated_cost_cny,
            6,
        )
        if abs(stage.total_estimated_cost_cny - expected_cost) > 0.000001:
            raise ValueError("候选方案总费用与回答、重排计量不一致")
        if stage.total_estimated_cost_complete != (
            report_metrics.estimated_cost_complete
            and stage.rerank_estimated_cost_complete
        ):
            raise ValueError("候选方案费用完整性标记不一致")
        if not self.profile.configuration.rerank.enabled:
            if any(
                (
                    stage.rerank_attempted_case_count,
                    stage.rerank_external_call_count,
                    stage.rerank_succeeded_case_count,
                    stage.rerank_fallback_case_count,
                    stage.rerank_observed_case_count,
                    stage.rerank_input_tokens,
                    stage.rerank_estimated_cost_cny,
                )
            ):
                raise ValueError("未启用重排的候选方案不能登记重排调用")
            if stage.mean_rerank_latency_ms is not None:
                raise ValueError("未启用重排的候选方案不能登记重排耗时")
        return self


class RagComparisonReport(StrictModel):
    schema_version: Literal["rag_comparison_report_v1"]
    report_version: str = Field(pattern=r"^[a-z0-9_]+_v[0-9]+$")
    run_kind: Literal["mock_comparison", "real_comparison"]
    generated_at: datetime
    dataset_version: str
    evaluation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: list[CandidateComparisonResult] = Field(min_length=2)

    @model_validator(mode="after")
    def candidates_share_frozen_assets(self) -> "RagComparisonReport":
        candidate_ids = [item.profile.candidate_id for item in self.candidates]
        fingerprints = [
            item.profile.configuration_fingerprint for item in self.candidates
        ]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("候选方案ID不能重复")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("候选方案完整配置不能重复")
        for item in self.candidates:
            report = item.evaluation_report
            if (
                report.dataset_version != self.dataset_version
                or report.evaluation_checksum != self.evaluation_checksum
                or report.corpus_version != self.corpus_version
                or report.corpus_checksum != self.corpus_checksum
            ):
                raise ValueError("候选方案未绑定同一评估集与语料")
        return self


class FrozenComparisonArtifact(StrictModel):
    role: Literal["baseline", "human_review_capture"]
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ComparisonHardLimits(StrictModel):
    max_cases_per_new_candidate: Literal[40]
    new_candidate_run_count: Literal[2]
    max_embedding_calls: Literal[80]
    max_answer_calls: Literal[80]
    max_rerank_calls: Literal[40]
    automatic_retries: Literal[0]
    max_total_tokens: Literal[1480000]
    max_estimated_cost_cny: Literal[4.4]
    stop_conditions: list[str] = Field(min_length=1)


class ComparisonPricingSnapshot(StrictModel):
    verified_on: Literal["2026-07-19"]
    deployment_scope: Literal["中国内地"]
    official_pricing_url: str
    qwen_model: Literal["qwen3-max"]
    qwen_input_price_per_million_tokens_cny: Literal[2.5]
    qwen_output_price_per_million_tokens_cny: Literal[10.0]
    embedding_model: Literal["text-embedding-v4"]
    embedding_price_per_million_tokens_cny: Literal[0.5]
    rerank_model: Literal["gte-rerank-v2"]
    rerank_price_per_million_tokens_cny: Literal[0.8]
    expected_cost_min_cny: Literal[0.6]
    expected_cost_max_cny: Literal[1.0]


class ComparisonRunPlan(StrictModel):
    schema_version: Literal["rag_comparison_plan_v1"]
    plan_version: str = Field(pattern=r"^[a-z0-9_]+_v[0-9]+$")
    generated_at: datetime
    dataset_version: str
    evaluation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_artifacts: list[FrozenComparisonArtifact] = Field(min_length=2)
    baseline_candidate_id: str
    new_candidate_ids: list[str] = Field(min_length=2, max_length=2)
    candidate_profiles: list[CandidateProfile] = Field(min_length=3, max_length=3)
    hard_limits: ComparisonHardLimits
    pricing: ComparisonPricingSnapshot
    paid_execution_available: Literal[True]
    requires_new_user_confirmation: Literal[True]
    production_flags_changed: Literal[False]

    @model_validator(mode="after")
    def candidate_plan_is_consistent(self) -> "ComparisonRunPlan":
        ids = [profile.candidate_id for profile in self.candidate_profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("运行计划候选方案ID不能重复")
        if self.baseline_candidate_id not in ids:
            raise ValueError("运行计划缺少冻结基线候选方案")
        if set(self.new_candidate_ids) != set(ids) - {self.baseline_candidate_id}:
            raise ValueError("新增候选方案与配置清单不一致")
        if len({item.role for item in self.frozen_artifacts}) != 2:
            raise ValueError("运行计划必须同时绑定基线与人工复核报告")
        return self
