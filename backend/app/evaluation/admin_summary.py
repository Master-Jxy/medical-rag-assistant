"""管理员可见的 corpus_v2/eval_v2 脱敏摘要。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from app.evaluation.corpus_v2 import load_evaluation_set, load_manifest, preflight_corpus_v2
from app.evaluation.eval_v2 import EvalV2Report
from app.evaluation.schemas import StrictModel


class CorpusEvaluationPublicSummary(StrictModel):
    schema_version: str = "corpus_evaluation_public_summary_v1"
    generated_at: datetime
    corpus_version: str
    corpus_checksum: str
    document_count: int = Field(ge=0)
    ready_document_count: int = Field(ge=0)
    pending_document_count: int = Field(ge=0)
    human_golden_case_count: int = Field(ge=0)
    coverage_gap_count: int = Field(ge=0)
    coverage_gaps: list[str]
    preflight_status: str
    issue_count: int = Field(ge=0)
    latest_dataset_version: str
    latest_report_version: str | None
    latest_run_kind: str | None
    no_cost_gate_passed: bool | None
    candidate_id: str | None
    promotion_decision: str | None


def build_public_summary(evaluation_root: Path) -> CorpusEvaluationPublicSummary:
    root = evaluation_root.resolve()
    manifest = load_manifest(root / "corpora" / "corpus_v2_manifest.json")
    evaluation_set = load_evaluation_set(root / "datasets" / "eval_v2.json")
    preflight = preflight_corpus_v2(manifest, evaluation_set, asset_root=root)
    report_path = root / "reports" / "eval_v2_fake_latest.json"
    report = None
    if report_path.is_file() and not report_path.is_symlink():
        report = EvalV2Report.model_validate_json(report_path.read_text(encoding="utf-8"))
    return CorpusEvaluationPublicSummary(
        generated_at=datetime.now(timezone.utc),
        corpus_version=manifest.corpus_version,
        corpus_checksum=manifest.corpus_checksum,
        document_count=manifest.document_count,
        ready_document_count=preflight.ready_document_count,
        pending_document_count=manifest.document_count - preflight.ready_document_count,
        human_golden_case_count=preflight.human_golden_case_count,
        coverage_gap_count=len(preflight.coverage_gaps),
        coverage_gaps=list(preflight.coverage_gaps),
        preflight_status=preflight.status,
        issue_count=len(preflight.issues),
        latest_dataset_version=evaluation_set.dataset_version,
        latest_report_version=report.report_version if report else None,
        latest_run_kind=report.run_kind if report else None,
        no_cost_gate_passed=report.no_cost_gate_passed if report else None,
        candidate_id=report.candidate_id if report else None,
        promotion_decision=report.promotion.decision if report else None,
    )
