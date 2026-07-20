"""Versioned contracts for the paid retrieval-ranking preflight and report."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.evaluation.retrieval_ranking_schemas import (
    RetrievalRankingCandidateResult,
    RetrievalRankingProfile,
)
from app.evaluation.schemas import StrictModel


class FrozenRankingArtifact(StrictModel):
    role: Literal[
        "baseline", "human_review", "rag_v1_2_comparison", "ranking_mock",
        "invalid_vector_port_attempt",
    ]
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RankingHardLimits(StrictModel):
    max_cases: Literal[40]
    max_embedding_calls: Literal[40]
    max_keyword_scans: Literal[40]
    max_rerank_calls: Literal[40]
    max_answer_calls: Literal[0]
    automatic_retries: Literal[0]
    embedding_tokens_reserved_per_call: Literal[512]
    rerank_tokens_reserved_per_call: Literal[30000]
    max_total_tokens: Literal[1220480]
    max_estimated_cost_cny: Literal[1.1]
    stop_conditions: list[str] = Field(min_length=1)


class RankingPricingSnapshot(StrictModel):
    verified_on: Literal["2026-07-20"]
    deployment_scope: Literal["中国内地"]
    official_pricing_url: str
    official_rerank_limits_url: str
    embedding_model: Literal["text-embedding-v4"]
    embedding_price_per_million_tokens_cny: Literal[0.5]
    rerank_model: Literal["gte-rerank-v2"]
    rerank_price_per_million_tokens_cny: Literal[0.8]
    expected_cost_min_cny: Literal[0.2]
    expected_cost_max_cny: Literal[0.6]


class RetrievalRankingRunPlan(StrictModel):
    schema_version: Literal["retrieval_ranking_plan_v1"]
    plan_version: Literal[
        "retrieval_ranking_preflight_v1",
        "retrieval_ranking_recovery_preflight_v2",
    ]
    generated_at: datetime
    dataset_version: str
    evaluation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_artifacts: list[FrozenRankingArtifact] = Field(min_length=4, max_length=5)
    candidate_profiles: list[RetrievalRankingProfile] = Field(min_length=4, max_length=4)
    hard_limits: RankingHardLimits
    pricing: RankingPricingSnapshot
    prior_attempt_estimated_cost_cny: float = Field(default=0.0, ge=0)
    cumulative_hard_ceiling_cny: float = Field(default=1.1, gt=0)
    paid_execution_available: Literal[True]
    requires_new_user_confirmation: Literal[True]
    production_flags_changed: Literal[False]

    @model_validator(mode="after")
    def fixed_candidates_are_unique(self) -> "RetrievalRankingRunPlan":
        ids = [item.candidate_id for item in self.candidate_profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("ranking candidate IDs must be unique")
        roles = {item.role for item in self.frozen_artifacts}
        if len(roles) != len(self.frozen_artifacts):
            raise ValueError("frozen artifact roles must be unique")
        if self.plan_version == "retrieval_ranking_preflight_v1":
            if len(roles) != 4 or "invalid_vector_port_attempt" in roles:
                raise ValueError("v1 must bind the original four frozen artifacts")
        elif "invalid_vector_port_attempt" not in roles or len(roles) != 5:
            raise ValueError("recovery v2 must bind the invalid first attempt")
        if (
            self.prior_attempt_estimated_cost_cny
            + self.hard_limits.max_estimated_cost_cny
            > self.cumulative_hard_ceiling_cny + 0.000001
        ):
            raise ValueError("cumulative ceiling cannot contain the planned recovery run")
        return self


class RankingCaseExecution(StrictModel):
    case_id: str = Field(pattern=r"^eval_[0-9]{3}$")
    vector_succeeded: bool
    keyword_succeeded: bool
    rerank_attempted: bool
    rerank_succeeded: bool
    hybrid_fallback_used: bool
    rerank_fallback_used: bool
    error_stages: list[Literal["vector", "keyword", "rerank"]]


class RankingUsageMetrics(StrictModel):
    embedding_calls: int = Field(ge=0, le=40)
    keyword_scans: int = Field(ge=0, le=40)
    rerank_calls: int = Field(ge=0, le=40)
    answer_calls: Literal[0]
    embedding_tokens_reserved: int = Field(ge=0)
    rerank_input_tokens: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0, le=1.1)


class RealRetrievalRankingReport(StrictModel):
    schema_version: Literal["retrieval_ranking_real_report_v1"]
    report_version: Literal["retrieval_ranking_real_v1"]
    run_kind: Literal["real_retrieval_ranking"]
    generated_at: datetime
    dataset_version: str
    evaluation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    usage: RankingUsageMetrics
    case_executions: list[RankingCaseExecution] = Field(min_length=40, max_length=40)
    candidates: list[RetrievalRankingCandidateResult] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def case_sets_match(self) -> "RealRetrievalRankingReport":
        expected = [item.case_id for item in self.case_executions]
        if len(expected) != len(set(expected)):
            raise ValueError("case execution IDs must be unique")
        if any([item.case_id for item in candidate.cases] != expected for candidate in self.candidates):
            raise ValueError("all candidates must use the same case order")
        return self
