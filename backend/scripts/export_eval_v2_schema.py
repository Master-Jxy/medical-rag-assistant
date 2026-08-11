"""导出 Stage 26.4 的版本化 JSON Schema。"""

import json
from pathlib import Path

from app.evaluation.admin_summary import CorpusEvaluationPublicSummary
from app.evaluation.corpus_v2 import (
    CorpusV2Manifest,
    CorpusV2PreflightReport,
    CorpusV2PreflightSummary,
    EvaluationSetV2,
)
from app.evaluation.eval_v2 import EvalV2Report

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "schemas"
SCHEMAS = {
    "corpus_v2_manifest.schema.json": CorpusV2Manifest,
    "evaluation_set_v2.schema.json": EvaluationSetV2,
    "corpus_v2_preflight_summary.schema.json": CorpusV2PreflightSummary,
    "corpus_v2_strict_preflight.schema.json": CorpusV2PreflightReport,
    "eval_v2_report.schema.json": EvalV2Report,
    "corpus_evaluation_public_summary.schema.json": CorpusEvaluationPublicSummary,
}


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for file_name, model in SCHEMAS.items():
        rendered = json.dumps(
            model.model_json_schema(), ensure_ascii=False, indent=2
        ) + "\n"
        output = SCHEMA_DIR / file_name
        output.write_text(rendered, encoding="utf-8")
        print(f"written={output}")


if __name__ == "__main__":
    main()
