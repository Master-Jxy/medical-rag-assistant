"""生成三套固定候选方案的无费用Mock对比报告。"""

import json
from pathlib import Path

from app.evaluation.comparison import build_mock_comparison
from app.evaluation.schemas import CorpusManifest, EvaluationSet

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "reports" / "rag_v1_2_mock_comparison_v1.json"


def load_assets() -> tuple[EvaluationSet, CorpusManifest, dict]:
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
    return evaluation_set, corpus, categories


def build_report():
    evaluation_set, corpus, categories = load_assets()
    return build_mock_comparison(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
    )


def main() -> None:
    report = build_report()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"written={OUTPUT}")
    for candidate in report.candidates:
        metrics = candidate.stage_metrics
        print(
            f"{candidate.profile.candidate_id}: "
            f"source_recall={candidate.evaluation_report.metrics.mean_source_recall}, "
            f"latency_ms={metrics.mean_total_pipeline_latency_ms}, "
            f"tokens={metrics.total_tokens}, "
            f"cost_cny={metrics.total_estimated_cost_cny}"
        )
    print("MOCK_ONLY：未调用Chroma、Embedding、Qwen或Reranker。")


if __name__ == "__main__":
    main()
