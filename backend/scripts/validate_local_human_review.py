"""校验被 Git 忽略的本地人工复核文件，并输出不含回答正文的差异。"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.evaluation.human_review import (
    LocalHumanReviewBundle,
    validate_and_compare_human_review,
)
from app.evaluation.schemas import EvaluationSet

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"
LOCAL_REVIEW_ROOT = (EVALUATION_ROOT / "local_reviews").resolve()
REPORT = EVALUATION_ROOT / "reports" / "current_baseline_v1.json"
DATASET = EVALUATION_ROOT / "datasets" / "eval_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path, default=REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = args.input.resolve()
    if LOCAL_REVIEW_ROOT not in path.parents:
        raise SystemExit("复核文件必须位于 backend/evaluation/local_reviews/ 内")
    bundle = LocalHumanReviewBundle.model_validate_json(path.read_text(encoding="utf-8"))
    evaluation_set = EvaluationSet.model_validate_json(DATASET.read_text(encoding="utf-8"))
    comparison = validate_and_compare_human_review(
        bundle=bundle,
        evaluation_set=evaluation_set,
        report_path=args.report.resolve(),
    )
    print(json.dumps(asdict(comparison), ensure_ascii=False, indent=2))
    print(f"expires_at={bundle.expires_at.isoformat()}")
    print("输出不包含问题、回答正文或人工备注。")


if __name__ == "__main__":
    main()
