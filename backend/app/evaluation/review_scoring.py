"""独立于 baseline_runner_v1 的可解释复核评分方法。"""

import re
from dataclasses import dataclass
from enum import StrEnum

BASELINE_V1_INSUFFICIENT_MESSAGE = "知识库资料不足，无法根据现有资料回答。"


class RefusalReviewClassification(StrEnum):
    ANSWER = "answer"
    REFUSE = "refuse"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class AliasKeyFactRubric:
    """人工审核后的概念等价短语；每组命中任意一个短语即覆盖该概念。"""

    concept_alias_groups: tuple[tuple[str, ...], ...]
    contradiction_phrases: tuple[str, ...] = ()


@dataclass(frozen=True)
class AliasKeyFactScore:
    matched_concept_count: int
    concept_count: int
    coverage: float
    contradiction_found: bool
    needs_review: bool


_HARD_REFUSAL_PHRASES = (
    "不能保证",
    "无法保证",
    "不能确诊",
    "无法确诊",
    "不能确认",
    "无法确认",
    "不能判断",
    "无法判断",
    "不能提供",
    "无法提供",
    "不能给出",
    "无法给出",
    "不能指导",
    "拒绝提供",
    "资料不足无法",
    "信息不足无法",
)

_AMBIGUOUS_BOUNDARY_PHRASES = (
    "不能自行",
    "不建议自行",
    "应由医生",
    "需要医生",
    "请咨询医生",
)


def normalize_review_text(value: str) -> str:
    """统一大小写并去除空白、标点，供透明短语匹配使用。"""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


def classify_refusal_v1(answer_text: str) -> RefusalReviewClassification:
    """复现首次真实基线的固定文案判定，不改变原报告。"""
    if BASELINE_V1_INSUFFICIENT_MESSAGE in answer_text:
        return RefusalReviewClassification.REFUSE
    return RefusalReviewClassification.ANSWER


def classify_refusal_v2(answer_text: str) -> RefusalReviewClassification:
    """识别明确拒绝措辞；软边界措辞保留给人工判断。"""
    normalized = normalize_review_text(answer_text)
    if normalize_review_text(BASELINE_V1_INSUFFICIENT_MESSAGE) in normalized:
        return RefusalReviewClassification.REFUSE
    if any(normalize_review_text(phrase) in normalized for phrase in _HARD_REFUSAL_PHRASES):
        return RefusalReviewClassification.REFUSE
    if any(
        normalize_review_text(phrase) in normalized
        for phrase in _AMBIGUOUS_BOUNDARY_PHRASES
    ):
        return RefusalReviewClassification.NEEDS_REVIEW
    return RefusalReviewClassification.ANSWER


def exact_key_fact_coverage_v1(answer_text: str, key_facts: tuple[str, ...]) -> float:
    """复现 baseline_runner_v1 的规范化整句精确子串评分。"""
    normalized_answer = " ".join(answer_text.split()).casefold()
    matched = sum(
        " ".join(fact.split()).casefold() in normalized_answer for fact in key_facts
    )
    return matched / len(key_facts)


def score_alias_key_fact_v2(
    answer_text: str, rubric: AliasKeyFactRubric
) -> AliasKeyFactScore:
    """按人工审核的概念别名组评分，并显式暴露矛盾短语。"""
    if not rubric.concept_alias_groups:
        raise ValueError("同义关键事实评分至少需要一个概念组")
    if any(not aliases for aliases in rubric.concept_alias_groups):
        raise ValueError("每个概念组至少需要一个等价短语")
    normalized = normalize_review_text(answer_text)
    matched = sum(
        any(normalize_review_text(alias) in normalized for alias in aliases)
        for aliases in rubric.concept_alias_groups
    )
    contradiction_found = any(
        normalize_review_text(phrase) in normalized
        for phrase in rubric.contradiction_phrases
    )
    coverage = matched / len(rubric.concept_alias_groups)
    return AliasKeyFactScore(
        matched_concept_count=matched,
        concept_count=len(rubric.concept_alias_groups),
        coverage=coverage,
        contradiction_found=contradiction_found,
        needs_review=contradiction_found,
    )
