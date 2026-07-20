"""评估集静态校验；不连接 Chroma、模型、MySQL 或线上会话。"""

from collections import Counter
from dataclasses import dataclass

from app.evaluation.schemas import (
    CorpusManifest,
    EvaluationCategory,
    EvaluationSet,
    ExpectedBehavior,
)


class EvaluationValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("评估集静态校验失败：\n- " + "\n- ".join(errors))


@dataclass(frozen=True)
class EvaluationValidationSummary:
    case_count: int
    category_counts: dict[str, int]
    referenced_document_count: int
    referenced_document_ids: tuple[str, ...]
    unreferenced_document_ids: tuple[str, ...]


def _normalized_question(question: str) -> str:
    return " ".join(question.split()).casefold()


def validate_evaluation_set(
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
) -> EvaluationValidationSummary:
    errors: list[str] = []
    cases = evaluation_set.cases
    configured_categories = {
        item["id"]: item["target_count"] for item in category_config["categories"]
    }
    category_counts = Counter(case.category.value for case in cases)

    if evaluation_set.dataset_version != category_config["dataset_version"]:
        errors.append("dataset_version 与分类配置不一致")
    if evaluation_set.corpus_version != corpus.corpus_version:
        errors.append("评估集 corpus_version 与语料清单不一致")
    if evaluation_set.corpus_checksum != corpus.corpus_checksum:
        errors.append("评估集 corpus_checksum 与语料清单不一致")
    if evaluation_set.corpus_version != category_config["corpus_version"]:
        errors.append("评估集 corpus_version 与分类配置不一致")
    if len(cases) != category_config["target_case_count"]:
        errors.append(
            f"题目总数应为 {category_config['target_case_count']}，实际为 {len(cases)}"
        )
    if dict(category_counts) != configured_categories:
        errors.append(
            f"分类配额不一致：期望 {configured_categories}，实际 {dict(category_counts)}"
        )

    case_ids = [case.case_id for case in cases]
    duplicate_case_ids = sorted(
        case_id for case_id, count in Counter(case_ids).items() if count > 1
    )
    if duplicate_case_ids:
        errors.append(f"case_id 重复：{duplicate_case_ids}")
    expected_case_ids = [f"eval_{index:03d}" for index in range(1, len(cases) + 1)]
    if case_ids != expected_case_ids:
        errors.append("case_id 必须按 eval_001 起连续递增并与文件顺序一致")

    normalized_questions = [_normalized_question(case.question) for case in cases]
    duplicate_questions = sorted(
        question
        for question, count in Counter(normalized_questions).items()
        if count > 1
    )
    if duplicate_questions:
        errors.append(f"问题文本重复：{duplicate_questions}")

    corpus_document_ids = {document.document_id for document in corpus.documents}
    referenced_document_ids: set[str] = set()
    for case in cases:
        prefix = case.case_id
        source_ids = case.expected_source_document_ids
        unknown_sources = sorted(set(source_ids) - corpus_document_ids)
        if unknown_sources:
            errors.append(f"{prefix} 引用了 corpus_v1 不存在的来源：{unknown_sources}")
        if len(source_ids) != len(set(source_ids)):
            errors.append(f"{prefix} 的来源 ID 重复")
        referenced_document_ids.update(source_ids)

        if not case.expected_key_facts or any(
            not fact.strip() for fact in case.expected_key_facts
        ):
            errors.append(f"{prefix} 必须登记非空的关键事实或拒答核验点")
        if not case.tags or any(not tag.strip() for tag in case.tags):
            errors.append(f"{prefix} 必须登记至少一个非空标签")

        if case.expected_behavior == ExpectedBehavior.REFUSE:
            if source_ids:
                errors.append(f"{prefix} 是拒答题，不得登记伪造来源")
        else:
            if not source_ids:
                errors.append(f"{prefix} 是回答题，必须登记来源")
            if not case.expected_key_facts:
                errors.append(f"{prefix} 是回答题，必须登记关键事实")

        if case.category == EvaluationCategory.SINGLE_DOCUMENT:
            if case.expected_behavior != ExpectedBehavior.ANSWER:
                errors.append(f"{prefix} 单文档题必须是回答题")
            if len(source_ids) != 1:
                errors.append(f"{prefix} 单文档题必须且只能登记一个来源")
        elif case.category == EvaluationCategory.MULTI_DOCUMENT:
            if case.expected_behavior != ExpectedBehavior.ANSWER:
                errors.append(f"{prefix} 多文档题必须是回答题")
            if len(source_ids) < 2:
                errors.append(f"{prefix} 多文档题至少需要两个预期来源")
        elif case.category == EvaluationCategory.CONVERSATIONAL_FOLLOW_UP:
            if case.expected_behavior != ExpectedBehavior.ANSWER:
                errors.append(f"{prefix} 连续追问题必须是回答题")
            if not case.history:
                errors.append(f"{prefix} 连续追问题必须提供历史对话")
        elif case.category in {
            EvaluationCategory.INSUFFICIENT_KNOWLEDGE,
            EvaluationCategory.SAFETY_BOUNDARY,
        }:
            if case.expected_behavior != ExpectedBehavior.REFUSE:
                errors.append(f"{prefix} 知识不足或安全边界题必须拒答")

        if (
            case.category != EvaluationCategory.CONVERSATIONAL_FOLLOW_UP
            and case.history
        ):
            errors.append(f"{prefix} 非连续追问题不应携带历史对话")

    if errors:
        raise EvaluationValidationError(errors)

    referenced = tuple(sorted(referenced_document_ids))
    unreferenced = tuple(sorted(corpus_document_ids - referenced_document_ids))
    return EvaluationValidationSummary(
        case_count=len(cases),
        category_counts=dict(category_counts),
        referenced_document_count=len(referenced),
        referenced_document_ids=referenced,
        unreferenced_document_ids=unreferenced,
    )
