"""导出未来评估题文件使用的版本化 JSON Schema。"""

import json
from pathlib import Path

from app.evaluation.report_schemas import BaselineReport
from app.evaluation.comparison_schemas import (
    ComparisonRunPlan,
    RagComparisonReport,
)
from app.evaluation.schemas import EvaluationSet
from app.evaluation.retrieval_ranking_schemas import RetrievalRankingReport
from app.evaluation.retrieval_ranking_real_schemas import (
    RealRetrievalRankingReport,
    RetrievalRankingRunPlan,
)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "schemas"
SCHEMAS = {
    "evaluation_set_v1.schema.json": EvaluationSet,
    "baseline_report_v1.schema.json": BaselineReport,
    "rag_comparison_report_v1.schema.json": RagComparisonReport,
    "rag_comparison_plan_v1.schema.json": ComparisonRunPlan,
    "retrieval_ranking_report_v1.schema.json": RetrievalRankingReport,
    "retrieval_ranking_plan_v1.schema.json": RetrievalRankingRunPlan,
    "retrieval_ranking_real_report_v1.schema.json": RealRetrievalRankingReport,
}


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for file_name, model in SCHEMAS.items():
        output = SCHEMA_DIR / file_name
        rendered = json.dumps(
            model.model_json_schema(), ensure_ascii=False, indent=2
        ) + "\n"
        output.write_text(rendered, encoding="utf-8")
        print(f"written={output}")


if __name__ == "__main__":
    main()
