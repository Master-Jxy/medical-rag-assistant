"""把不含正文的人工决策合并到受控本地回答文件。"""

import argparse
from pathlib import Path

from app.evaluation.human_review import (
    HumanReviewDecisionSet,
    LocalHumanReviewBundle,
    apply_human_review_decisions,
)
from app.evaluation.review_capture import replace_local_review_bundle
from app.evaluation.schemas import EvaluationSet
from scripts.validate_local_human_review import (
    DATASET,
    LOCAL_REVIEW_ROOT,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("local_review", type=Path)
    parser.add_argument("decisions", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    local_path = args.local_review.resolve()
    if LOCAL_REVIEW_ROOT not in local_path.parents:
        raise SystemExit("本地回答文件必须位于 backend/evaluation/local_reviews/ 内")
    bundle = LocalHumanReviewBundle.model_validate_json(
        local_path.read_text(encoding="utf-8")
    )
    decisions = HumanReviewDecisionSet.model_validate_json(
        args.decisions.read_text(encoding="utf-8")
    )
    evaluation_set = EvaluationSet.model_validate_json(
        DATASET.read_text(encoding="utf-8")
    )
    updated = apply_human_review_decisions(
        bundle=bundle,
        decisions=decisions,
        evaluation_set=evaluation_set,
    )
    replace_local_review_bundle(
        bundle=updated,
        output_path=local_path,
        local_review_root=LOCAL_REVIEW_ROOT,
    )
    print(f"updated={local_path}")
    print("人工决策文件和输出均不包含命令行正文回显。")


if __name__ == "__main__":
    main()
