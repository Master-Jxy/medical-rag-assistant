"""导出便于人工核对题目与来源的 eval_v1 Markdown 清单。"""

import json
from pathlib import Path

from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.evaluation.validation import validate_evaluation_set

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "reviews" / "eval_v1_review.md"


def escaped(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> None:
    corpus = CorpusManifest.model_validate_json(
        (EVALUATION_ROOT / "corpora" / "corpus_v1.json").read_text(encoding="utf-8")
    )
    evaluation_set = EvaluationSet.model_validate_json(
        (EVALUATION_ROOT / "datasets" / "eval_v1.json").read_text(encoding="utf-8")
    )
    categories = json.loads(
        (EVALUATION_ROOT / "categories_v1.json").read_text(encoding="utf-8")
    )
    summary = validate_evaluation_set(evaluation_set, corpus, categories)
    names_by_id = {
        document.document_id: document.original_name for document in corpus.documents
    }
    lines = [
        "# eval_v1 人工审查清单",
        "",
        f"- 题目总数：{summary.case_count}",
        f"- 来源覆盖：{summary.referenced_document_count}/{corpus.document_count} 份 corpus_v1 文档",
        f"- 语料校验值：`{evaluation_set.corpus_checksum}`",
        "- 拒答题的预期来源均为空；表中的“无（拒答）”不是检索来源。",
        "",
        "| case_id | 类别 | 行为 | 问题 | 预期来源 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in evaluation_set.cases:
        sources = "；".join(
            names_by_id[source_id] for source_id in case.expected_source_document_ids
        ) or "无（拒答）"
        lines.append(
            f"| {case.case_id} | {case.category.value} | "
            f"{case.expected_behavior.value} | {escaped(case.question)} | "
            f"{escaped(sources)} |"
        )
    lines.extend(
        [
            "",
            "## 分类配额",
            "",
            *[
                f"- `{name}`：{count} 题"
                for name, count in summary.category_counts.items()
            ],
            "",
            "## 未覆盖文档",
            "",
            "无。" if not summary.unreferenced_document_ids else "\n".join(
                f"- {names_by_id[document_id]}"
                for document_id in summary.unreferenced_document_ids
            ),
            "",
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written={OUTPUT}")


if __name__ == "__main__":
    main()
