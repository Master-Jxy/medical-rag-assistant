"""运行可重复的假适配器干跑并保存版本化报告。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.fake_adapters import (
    FixedFakeAnswerAdapter,
    FixedFakeRetrievalAdapter,
)
from app.evaluation.runner import run_evaluation
from app.evaluation.schemas import CorpusManifest, EvaluationSet

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "reports" / "dry_run_v1.json"


def build_fake_dry_run():
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
    category_config = json.loads(
        (EVALUATION_ROOT / "categories_v1.json").read_text(encoding="utf-8")
    )
    retrieval = FixedFakeRetrievalAdapter(
        evaluation_set,
        failure_case_ids={"eval_039"},
    )
    answer = FixedFakeAnswerAdapter(
        evaluation_set,
        failure_case_ids={"eval_040"},
        usage_missing_case_ids={"eval_036"},
    )
    return run_evaluation(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=category_config,
        retrieval_port=retrieval,
        answer_port=answer,
        report_version="dry_run_v1",
        run_kind="fake_dry_run",
        generated_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )


def main() -> None:
    report = build_fake_dry_run()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"written={OUTPUT}")
    print(
        f"cases={report.metrics.case_count}, "
        f"completed={report.metrics.completed_case_count}, "
        f"failed={report.metrics.failed_case_count}"
    )
    print(
        f"source_recall={report.metrics.mean_source_recall}, "
        f"refusal_accuracy={report.metrics.refusal_accuracy}, "
        f"key_fact_coverage={report.metrics.mean_key_fact_coverage}"
    )
    print(
        f"usage_reported={report.metrics.usage_reported_case_count}, "
        f"usage_missing={report.metrics.usage_missing_case_count}, "
        f"estimated_cost_complete={report.metrics.estimated_cost_complete}"
    )


if __name__ == "__main__":
    main()
