"""Validate corpus_v2 assets and emit a no-cost preflight summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.corpus_v2 import (
    build_cleaning_dedup_report,
    build_coverage_matrix,
    build_preflight_summary,
    load_evaluation_set,
    load_manifest,
    render_preflight_markdown,
    validate_corpus_v2_assets,
)

EVALUATION_ROOT = Path(__file__).resolve().parents[1] / "evaluation"
DEFAULT_MANIFEST = EVALUATION_ROOT / "corpora" / "corpus_v2_manifest.json"
DEFAULT_DATASET = EVALUATION_ROOT / "datasets" / "eval_v2.json"
DEFAULT_JSON_SUMMARY = EVALUATION_ROOT / "plans" / "corpus_v2_no_cost_preflight_v1.json"
DEFAULT_MARKDOWN_SUMMARY = EVALUATION_ROOT / "reviews" / "corpus_v2_preflight_summary.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_SUMMARY)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_SUMMARY)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate only and compare default summaries if they exist.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    evaluation_set = load_evaluation_set(args.dataset)
    validate_corpus_v2_assets(manifest, evaluation_set)
    coverage = build_coverage_matrix(manifest, evaluation_set)
    dedup = build_cleaning_dedup_report(manifest)
    summary = build_preflight_summary(manifest, evaluation_set, coverage)
    if not summary.no_cost_gate_passed or any(summary.provider_calls.model_dump().values()):
        raise SystemExit("corpus_v2 preflight attempted to reserve real provider calls")

    payload = json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    markdown = render_preflight_markdown(summary)
    if args.check:
        if args.json_output.is_file() and args.json_output.read_text(encoding="utf-8") != payload:
            raise SystemExit("corpus_v2 JSON preflight summary is stale")
        if args.markdown_output.is_file() and args.markdown_output.read_text(encoding="utf-8") != markdown:
            raise SystemExit("corpus_v2 Markdown preflight summary is stale")
    else:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload, encoding="utf-8")
        args.markdown_output.write_text(markdown, encoding="utf-8")
    print(
        "corpus_v2 OK: "
        f"documents={manifest.document_count}; "
        f"cases={len(evaluation_set.cases)}; "
        f"coverage_gaps={len(coverage.gaps)}; "
        f"dedup_unknown={len(dedup.skipped_unknown_content_ids)}; "
        "provider_calls=0"
    )


if __name__ == "__main__":
    main()
