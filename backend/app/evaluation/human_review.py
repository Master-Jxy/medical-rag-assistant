"""包含回答正文的本地人工复核契约与脱敏汇总。"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.evaluation.report_schemas import BaselineReport
from app.evaluation.schemas import EvaluationSet, StrictModel

MAX_LOCAL_REVIEW_RETENTION = timedelta(days=7)


class HumanBehaviorDecision(StrEnum):
    ANSWER = "answer"
    REFUSE = "refuse"
    UNCERTAIN = "uncertain"


class HumanFactDecision(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNCERTAIN = "uncertain"


class LocalHumanReviewItem(StrictModel):
    case_id: str = Field(pattern=r"^eval_[0-9]{3}$")
    answer_text: str = Field(min_length=1)
    behavior_decision: HumanBehaviorDecision
    key_fact_decisions: list[HumanFactDecision]
    reviewer_notes: str = Field(default="", max_length=1000)


class LocalHumanReviewBundle(StrictModel):
    schema_version: Literal["local_human_review_v1"]
    dataset_version: str
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    expires_at: datetime
    items: list[LocalHumanReviewItem] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def retention_is_bounded(self) -> "LocalHumanReviewBundle":
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("人工复核时间必须包含时区")
        retention = self.expires_at - self.created_at
        if retention <= timedelta(0):
            raise ValueError("expires_at 必须晚于 created_at")
        if retention > MAX_LOCAL_REVIEW_RETENTION:
            raise ValueError("包含回答正文的本地复核文件最多保留7天")
        ids = [item.case_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("人工复核 case_id 不能重复")
        return self


class HumanReviewDecisionItem(StrictModel):
    case_id: str = Field(pattern=r"^eval_[0-9]{3}$")
    behavior_decision: HumanBehaviorDecision
    key_fact_decisions: list[HumanFactDecision]
    reviewer_notes: str = Field(default="", max_length=1000)


class HumanReviewDecisionSet(StrictModel):
    schema_version: Literal["human_review_decisions_v1"]
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[HumanReviewDecisionItem] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> "HumanReviewDecisionSet":
        ids = [item.case_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("人工决策 case_id 不能重复")
        return self


@dataclass(frozen=True)
class HumanReviewComparison:
    reviewed_case_count: int
    behavior_decided_case_count: int
    behavior_uncertain_case_count: int
    original_behavior_accuracy: float | None
    human_behavior_accuracy: float | None
    original_mean_key_fact_coverage: float | None
    human_mean_key_fact_coverage: float | None
    fact_uncertain_count: int


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_human_review_decisions(
    *,
    bundle: LocalHumanReviewBundle,
    decisions: HumanReviewDecisionSet,
    evaluation_set: EvaluationSet,
) -> LocalHumanReviewBundle:
    if decisions.source_report_sha256 != bundle.source_report_sha256:
        raise ValueError("人工决策与本地回答绑定的报告哈希不一致")
    bundle_ids = {item.case_id for item in bundle.items}
    decision_by_id = {item.case_id: item for item in decisions.items}
    if set(decision_by_id) != bundle_ids:
        raise ValueError("人工决策必须完整覆盖本地回答题号")
    cases = {case.case_id: case for case in evaluation_set.cases}
    updated_items: list[LocalHumanReviewItem] = []
    for item in bundle.items:
        decision = decision_by_id[item.case_id]
        case = cases.get(item.case_id)
        if case is None:
            raise ValueError(f"未知人工决策题号：{item.case_id}")
        if len(decision.key_fact_decisions) != len(case.expected_key_facts):
            raise ValueError(f"{item.case_id} 的关键事实人工决策数量不一致")
        updated_items.append(
            item.model_copy(
                update={
                    "behavior_decision": decision.behavior_decision,
                    "key_fact_decisions": decision.key_fact_decisions,
                    "reviewer_notes": decision.reviewer_notes,
                }
            )
        )
    return bundle.model_copy(update={"items": updated_items})


def validate_and_compare_human_review(
    *,
    bundle: LocalHumanReviewBundle,
    evaluation_set: EvaluationSet,
    report_path: Path,
    now: datetime | None = None,
) -> HumanReviewComparison:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("当前时间必须包含时区")
    if current_time > bundle.expires_at:
        raise ValueError("本地人工复核文件已过期，必须删除")
    if bundle.dataset_version != evaluation_set.dataset_version:
        raise ValueError("人工复核 dataset_version 不一致")
    if bundle.corpus_checksum != evaluation_set.corpus_checksum:
        raise ValueError("人工复核 corpus_checksum 不一致")
    if bundle.source_report_sha256 != sha256_file(report_path):
        raise ValueError("人工复核绑定的真实基线报告哈希不一致")

    report = BaselineReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    if report.dataset_version != evaluation_set.dataset_version:
        raise ValueError("真实报告 dataset_version 与评估集不一致")
    if report.corpus_checksum != evaluation_set.corpus_checksum:
        raise ValueError("真实报告 corpus_checksum 与评估集不一致")

    cases = {case.case_id: case for case in evaluation_set.cases}
    report_results = {item.case_id: item for item in report.cases}
    original_behavior: list[bool] = []
    human_behavior: list[bool] = []
    original_facts: list[float] = []
    human_facts: list[float] = []
    behavior_uncertain = 0
    fact_uncertain = 0

    for item in bundle.items:
        case = cases.get(item.case_id)
        result = report_results.get(item.case_id)
        if case is None or result is None:
            raise ValueError(f"未知人工复核题号：{item.case_id}")
        if len(item.key_fact_decisions) != len(case.expected_key_facts):
            raise ValueError(f"{item.case_id} 的关键事实人工标注数量不一致")
        if result.behavior_correct is not None:
            original_behavior.append(result.behavior_correct)
        if result.key_fact_coverage is not None:
            original_facts.append(result.key_fact_coverage)

        if item.behavior_decision == HumanBehaviorDecision.UNCERTAIN:
            behavior_uncertain += 1
        else:
            human_behavior.append(
                item.behavior_decision.value == case.expected_behavior.value
            )
        if HumanFactDecision.UNCERTAIN in item.key_fact_decisions:
            fact_uncertain += sum(
                decision == HumanFactDecision.UNCERTAIN
                for decision in item.key_fact_decisions
            )
        else:
            human_facts.append(
                sum(
                    decision == HumanFactDecision.MET
                    for decision in item.key_fact_decisions
                )
                / len(item.key_fact_decisions)
            )

    return HumanReviewComparison(
        reviewed_case_count=len(bundle.items),
        behavior_decided_case_count=len(human_behavior),
        behavior_uncertain_case_count=behavior_uncertain,
        original_behavior_accuracy=_mean_bool(original_behavior),
        human_behavior_accuracy=_mean_bool(human_behavior),
        original_mean_key_fact_coverage=_mean_float(original_facts),
        human_mean_key_fact_coverage=_mean_float(human_facts),
        fact_uncertain_count=fact_uncertain,
    )


def _mean_bool(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _mean_float(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
