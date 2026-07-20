"""生成任务7.7第一小步的确定性无费用排序报告。"""

import json
from pathlib import Path

from app.evaluation.retrieval_ranking import build_mock_retrieval_ranking_report
from scripts.run_mock_comparison import load_assets

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
OUTPUT = EVALUATION_ROOT / "reports" / "retrieval_ranking_mock_v1.json"


def build_report():
    evaluation_set, corpus, categories = load_assets()
    return build_mock_retrieval_ranking_report(
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
        metrics = candidate.metrics
        print(
            f"{candidate.profile.candidate_id}: "
            f"recall@4={metrics.mean_source_recall_at_4}, "
            f"recall@10={metrics.mean_source_recall_at_10}, "
            f"mrr@4={metrics.mean_mrr_at_4}, "
            f"ndcg@4={metrics.mean_ndcg_at_4}, "
            f"duplicate@4={metrics.mean_duplicate_chunk_ratio_at_4}"
        )
    print("MOCK_ONLY：未读取Chroma，未调用Embedding、Reranker或Qwen。")


if __name__ == "__main__":
    main()
