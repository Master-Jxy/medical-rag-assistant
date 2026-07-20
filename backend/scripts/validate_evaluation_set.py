"""静态校验 eval_v1；不会运行检索或调用任何模型。"""

import argparse
import json
from pathlib import Path

from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.evaluation.validation import validate_evaluation_set

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=EVALUATION_ROOT / "datasets" / "eval_v1.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    corpus = CorpusManifest.model_validate_json(
        (EVALUATION_ROOT / "corpora" / "corpus_v1.json").read_text(encoding="utf-8")
    )
    evaluation_set = EvaluationSet.model_validate_json(
        args.dataset.read_text(encoding="utf-8")
    )
    categories = json.loads(
        (EVALUATION_ROOT / "categories_v1.json").read_text(encoding="utf-8")
    )
    summary = validate_evaluation_set(evaluation_set, corpus, categories)
    category_text = ", ".join(
        f"{name}={count}" for name, count in summary.category_counts.items()
    )
    print(f"eval_v1 OK: cases={summary.case_count}; {category_text}")
    print(
        f"source_coverage={summary.referenced_document_count}/{corpus.document_count}; "
        f"unreferenced={len(summary.unreferenced_document_ids)}"
    )


if __name__ == "__main__":
    main()
