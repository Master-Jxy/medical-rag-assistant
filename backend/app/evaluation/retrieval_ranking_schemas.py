"""任务7.7候选池排序实验的版本化数据契约。"""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.evaluation.schemas import EvaluationCategory, StrictModel


class RetrievalRankingConfiguration(StrictModel):
    profile_version: Literal["retrieval_ranking_profile_v1"]
    candidate_pool_size: Literal[12]
    max_chunks_per_document: Literal[2]
    final_top_k: Literal[4]
    vector_adapter: str
    keyword_adapter: str
    retrieval_mode: Literal["vector", "hybrid_rrf"]
    vector_weight: float = Field(ge=0, le=1)
    keyword_weight: float = Field(ge=0, le=1)
    rrf_k: int = Field(ge=1, le=1000)
    document_diversity_enabled: bool
    rerank_enabled: bool
    rerank_adapter: str
    rerank_model: str
    shared_vector_and_keyword_inputs: Literal[True]


def calculate_ranking_configuration_fingerprint(
    configuration: RetrievalRankingConfiguration,
) -> str:
    canonical = json.dumps(
        configuration.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RetrievalRankingProfile(StrictModel):
    candidate_id: Literal[
        "vector_top4_reference",
        "vector_wide_diverse_v1",
        "hybrid_wide_diverse_v1",
        "hybrid_wide_diverse_rerank_v1",
    ]
    display_name: str = Field(min_length=1, max_length=100)
    configuration: RetrievalRankingConfiguration
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def fingerprint_matches_configuration(self) -> "RetrievalRankingProfile":
        expected = calculate_ranking_configuration_fingerprint(self.configuration)
        if self.configuration_fingerprint != expected:
            raise ValueError("排序候选配置指纹与完整配置不一致")
        return self


class RetrievalRankingCaseMetrics(StrictModel):
    source_recall_at_4: float | None = Field(default=None, ge=0, le=1)
    source_recall_at_10: float | None = Field(default=None, ge=0, le=1)
    full_source_hit_at_4: bool | None = None
    full_source_hit_at_10: bool | None = None
    mrr_at_4: float | None = Field(default=None, ge=0, le=1)
    ndcg_at_4: float | None = Field(default=None, ge=0, le=1)
    unique_document_count_at_4: int | None = Field(default=None, ge=0, le=4)
    duplicate_chunk_ratio_at_4: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def is_fully_scored_or_fully_excluded(self) -> "RetrievalRankingCaseMetrics":
        values = tuple(self.__dict__.values())
        if any(value is None for value in values) and not all(
            value is None for value in values
        ):
            raise ValueError("单题排序指标必须全部计分或全部为空")
        return self


class RetrievalRankingCaseResult(StrictModel):
    case_id: str = Field(pattern=r"^eval_[0-9]{3}$")
    category: EvaluationCategory
    expected_source_document_ids: list[str]
    ranked_document_ids_at_10: list[str] = Field(max_length=10)
    final_chunk_document_ids: list[str] = Field(max_length=4)
    metrics: RetrievalRankingCaseMetrics

    @model_validator(mode="after")
    def source_expectation_matches_scoring(self) -> "RetrievalRankingCaseResult":
        excluded = self.metrics.source_recall_at_4 is None
        if bool(self.expected_source_document_ids) == excluded:
            raise ValueError("空期望来源题必须排除排序计分，回答题必须计分")
        return self


class RetrievalRankingAggregateMetrics(StrictModel):
    case_count: int = Field(ge=0)
    scored_case_count: int = Field(ge=0)
    mean_source_recall_at_4: float | None = Field(default=None, ge=0, le=1)
    mean_source_recall_at_10: float | None = Field(default=None, ge=0, le=1)
    full_source_hit_rate_at_4: float | None = Field(default=None, ge=0, le=1)
    full_source_hit_rate_at_10: float | None = Field(default=None, ge=0, le=1)
    mean_mrr_at_4: float | None = Field(default=None, ge=0, le=1)
    mean_ndcg_at_4: float | None = Field(default=None, ge=0, le=1)
    mean_unique_document_count_at_4: float | None = Field(
        default=None, ge=0, le=4
    )
    mean_duplicate_chunk_ratio_at_4: float | None = Field(
        default=None, ge=0, le=1
    )


class RetrievalRankingCategoryMetrics(RetrievalRankingAggregateMetrics):
    category: EvaluationCategory


class RetrievalRankingCandidateResult(StrictModel):
    profile: RetrievalRankingProfile
    metrics: RetrievalRankingAggregateMetrics
    category_metrics: list[RetrievalRankingCategoryMetrics]
    cases: list[RetrievalRankingCaseResult]

    @model_validator(mode="after")
    def counts_and_case_ids_are_consistent(self) -> "RetrievalRankingCandidateResult":
        if self.metrics.case_count != len(self.cases):
            raise ValueError("候选case_count必须与逐题结果一致")
        if self.metrics.scored_case_count != sum(
            item.metrics.source_recall_at_4 is not None for item in self.cases
        ):
            raise ValueError("候选scored_case_count必须与逐题结果一致")
        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("候选逐题结果不能包含重复case_id")
        categories = [item.category for item in self.category_metrics]
        if set(categories) != set(EvaluationCategory) or len(categories) != len(
            EvaluationCategory
        ):
            raise ValueError("候选必须登记全部评估类别且不能重复")
        return self


class RetrievalRankingReport(StrictModel):
    schema_version: Literal["retrieval_ranking_report_v1"]
    report_version: Literal["retrieval_ranking_mock_v1"]
    run_kind: Literal["mock_retrieval_ranking"]
    generated_at: datetime
    dataset_version: str
    evaluation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: list[RetrievalRankingCandidateResult] = Field(
        min_length=4, max_length=4
    )

    @model_validator(mode="after")
    def candidate_set_and_cases_are_consistent(self) -> "RetrievalRankingReport":
        expected_ids = {
            "vector_top4_reference",
            "vector_wide_diverse_v1",
            "hybrid_wide_diverse_v1",
            "hybrid_wide_diverse_rerank_v1",
        }
        candidate_ids = {item.profile.candidate_id for item in self.candidates}
        if candidate_ids != expected_ids or len(self.candidates) != len(candidate_ids):
            raise ValueError("排序报告必须包含四个固定且唯一的候选")
        fingerprints = {
            item.profile.configuration_fingerprint for item in self.candidates
        }
        if len(fingerprints) != len(self.candidates):
            raise ValueError("排序候选完整配置不能重复")
        case_id_sets = [tuple(item.case_id for item in c.cases) for c in self.candidates]
        if any(case_ids != case_id_sets[0] for case_ids in case_id_sets[1:]):
            raise ValueError("四个排序候选必须使用相同题目顺序")
        return self
