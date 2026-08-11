"""运行 Stage 26.4 的 corpus_v2/eval_v2 无费用门禁。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.corpus_v2 import load_evaluation_set, load_manifest
from app.evaluation.eval_v2 import run_eval_v2

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"
MANIFEST_PATH = EVALUATION_ROOT / "corpora" / "corpus_v2_manifest.json"
DATASET_PATH = EVALUATION_ROOT / "datasets" / "eval_v2.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic no-cost eval_v2; never calls real providers.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path. The default only prints the report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_manifest(MANIFEST_PATH)
    evaluation_set = load_evaluation_set(DATASET_PATH)
    report = run_eval_v2(
        manifest=manifest,
        evaluation_set=evaluation_set,
        asset_root=EVALUATION_ROOT,
        generated_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    rendered = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        reports_root = (EVALUATION_ROOT / "reports").resolve()
        try:
            output.relative_to(reports_root)
        except ValueError as exc:
            raise SystemExit("output must stay inside backend/evaluation/reports") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"written={output}")
    print(rendered, end="")


if __name__ == "__main__":
    main()
