"""离线评估基线报告的版本化数据契约。"""

from datetime import datetime

from typing import Literal

from pydantic import Field, model_validator

from app.evaluation.schemas import (
    EvaluationCategory,
    ExpectedBehavior,
    StrictModel,
)


class BaselineTokenUsage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_cny: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def total_matches_parts(self) -> "BaselineTokenUsage":
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens 必须等于 input_tokens + output_tokens")
        return self


class BaselineCaseResult(StrictModel):
    case_id: str
    category: EvaluationCategory
    expected_behavior: ExpectedBehavior
    status: Literal["completed", "failed"]
    retrieved_source_document_ids: list[str]
    actual_behavior: ExpectedBehavior | None
    source_recall: float | None = Field(default=None, ge=0, le=1)
    source_full_hit: bool | None
    behavior_correct: bool | None
    expected_key_fact_count: int = Field(ge=0)
    matched_key_fact_count: int = Field(ge=0)
    key_fact_coverage: float | None = Field(default=None, ge=0, le=1)
    retrieval_latency_ms: float | None = Field(default=None, ge=0)
    answer_latency_ms: float | None = Field(default=None, ge=0)
    total_latency_ms: float | None = Field(default=None, ge=0)
    usage: BaselineTokenUsage | None
    error_stage: Literal["retrieval", "answer"] | None
    error_type: str | None

    @model_validator(mode="after")
    def status_fields_are_consistent(self) -> "BaselineCaseResult":
        if self.status == "completed":
            if self.actual_behavior is None or self.behavior_correct is None:
                raise ValueError("completed 结果必须包含实际行为和行为评分")
            if self.answer_latency_ms is None or self.total_latency_ms is None:
                raise ValueError("completed 结果必须包含回答和总耗时")
            if self.key_fact_coverage is None:
                raise ValueError("completed 结果必须包含关键事实覆盖率")
            if self.error_stage is not None or self.error_type is not None:
                raise ValueError("completed 结果不能包含错误信息")
        else:
            if self.error_stage is None or not self.error_type:
                raise ValueError("failed 结果必须包含错误阶段和类型")
            if self.actual_behavior is not None or self.behavior_correct is not None:
                raise ValueError("failed 结果不能伪造回答行为评分")
        if self.matched_key_fact_count > self.expected_key_fact_count:
            raise ValueError("命中关键事实数量不能超过期望数量")
        return self


class BaselineMetrics(StrictModel):
    case_count: int = Field(ge=0)
    completed_case_count: int = Field(ge=0)
    failed_case_count: int = Field(ge=0)
    source_scored_case_count: int = Field(ge=0)
    mean_source_recall: float | None = Field(default=None, ge=0, le=1)
    full_source_hit_rate: float | None = Field(default=None, ge=0, le=1)
    behavior_scored_case_count: int = Field(ge=0)
    behavior_accuracy: float | None = Field(default=None, ge=0, le=1)
    refusal_scored_case_count: int = Field(ge=0)
    refusal_accuracy: float | None = Field(default=None, ge=0, le=1)
    key_fact_scored_case_count: int = Field(ge=0)
    mean_key_fact_coverage: float | None = Field(default=None, ge=0, le=1)
    retrieval_observed_case_count: int = Field(ge=0)
    mean_retrieval_latency_ms: float | None = Field(default=None, ge=0)
    answer_observed_case_count: int = Field(ge=0)
    mean_answer_latency_ms: float | None = Field(default=None, ge=0)
    usage_reported_case_count: int = Field(ge=0)
    usage_missing_case_count: int = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_cny: float = Field(ge=0)
    estimated_cost_complete: bool

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "BaselineMetrics":
        if self.case_count != self.completed_case_count + self.failed_case_count:
            raise ValueError("case_count 必须等于完成数与失败数之和")
        if self.total_tokens != self.total_input_tokens + self.total_output_tokens:
            raise ValueError("总 Token 数必须等于输入与输出之和")
        if (
            self.completed_case_count
            != self.usage_reported_case_count + self.usage_missing_case_count
        ):
            raise ValueError("完成题数必须等于有计量与缺失计量题数之和")
        return self


class BaselineScoringMethods(StrictModel):
    source_recall: Literal["expected_document_id_recall_v1"]
    behavior: Literal["expected_behavior_exact_match_v1"]
    key_fact: Literal["normalized_exact_substring_v1"]


class BaselineReport(StrictModel):
    schema_version: Literal["baseline_report_v1"]
    report_version: str = Field(pattern=r"^[a-z0-9_]+_v[0-9]+$")
    run_kind: Literal["fake_dry_run", "current_baseline", "candidate_comparison"]
    runner_version: Literal["baseline_runner_v1"]
    generated_at: datetime
    dataset_version: str
    evaluation_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_adapter: str = Field(min_length=1)
    answer_adapter: str = Field(min_length=1)
    scoring_methods: BaselineScoringMethods
    metrics: BaselineMetrics
    cases: list[BaselineCaseResult]

    @model_validator(mode="after")
    def case_count_matches_results(self) -> "BaselineReport":
        if self.metrics.case_count != len(self.cases):
            raise ValueError("报告题目数必须与 cases 数量一致")
        return self
