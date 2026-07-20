"""生成任务7.6付费候选对比的纯本地受控运行计划。"""

import json
from pathlib import Path

from app.evaluation.comparison_preflight import build_comparison_run_plan
from app.evaluation.schemas import CorpusManifest, EvaluationSet

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "plans" / "rag_v1_2_preflight_v1.json"


def build_plan():
    evaluation_set = EvaluationSet.model_validate_json(
        (EVALUATION_ROOT / "datasets" / "eval_v1.json").read_text(
            encoding="utf-8"
        )
    )
    corpus = CorpusManifest.model_validate_json(
        (EVALUATION_ROOT / "corpora" / "corpus_v1.json").read_text(
            encoding="utf-8"
        )
    )
    categories = json.loads(
        (EVALUATION_ROOT / "categories_v1.json").read_text(encoding="utf-8")
    )
    return build_comparison_run_plan(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        baseline_path=EVALUATION_ROOT / "reports" / "current_baseline_v1.json",
        human_capture_path=(
            EVALUATION_ROOT / "reports" / "human_review_capture_v1.json"
        ),
    )


def main() -> None:
    plan = build_plan()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"written={OUTPUT}")
    print(json.dumps(plan.hard_limits.model_dump(), ensure_ascii=False, indent=2))
    print("PLAN_ONLY：只更新版本化计划，未调用任何外部服务。")


if __name__ == "__main__":
    main()
