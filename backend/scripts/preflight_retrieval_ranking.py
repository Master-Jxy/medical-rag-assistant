"""Build the versioned, no-cost task 7.7 retrieval-ranking plan."""

import json
from pathlib import Path

from app.evaluation.retrieval_ranking_preflight import (
    build_retrieval_ranking_recovery_plan,
)
from scripts.run_mock_comparison import load_assets

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "plans" / "retrieval_ranking_recovery_preflight_v2.json"


def build_plan():
    evaluation_set, corpus, categories = load_assets()
    return build_retrieval_ranking_recovery_plan(
        evaluation_set=evaluation_set, corpus=corpus, category_config=categories
    )


def main() -> None:
    plan = build_plan()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"written={OUTPUT}")
    print("PLAN_ONLY: no Embedding, Reranker, or Qwen call was made")


if __name__ == "__main__":
    main()
