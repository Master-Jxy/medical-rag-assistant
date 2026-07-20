import json
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.comparison_schemas import (
    ComparisonRunPlan,
    RagComparisonReport,
)
from app.evaluation.comparison_preflight import build_comparison_run_plan
from scripts.preflight_rag_v1_2_comparison import build_plan
from scripts.run_mock_comparison import build_report

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"


def test_mock_comparison_uses_same_assets_and_unique_configuration_fingerprints() -> None:
    report = build_report()

    assert report.schema_version == "rag_comparison_report_v1"
    assert report.run_kind == "mock_comparison"
    assert [item.profile.candidate_id for item in report.candidates] == [
        "vector_baseline_v1",
        "hybrid_rrf_v1",
        "hybrid_rrf_rerank_v1",
    ]
    assert len(
        {
            item.profile.configuration_fingerprint
            for item in report.candidates
        }
    ) == 3
    assert all(
        item.evaluation_report.evaluation_checksum == report.evaluation_checksum
        and item.evaluation_report.corpus_checksum == report.corpus_checksum
        and item.evaluation_report.metrics.case_count == 40
        for item in report.candidates
    )


def test_mock_comparison_records_retrieval_rerank_answer_cost_and_latency() -> None:
    report = build_report()
    baseline, hybrid, reranked = report.candidates

    assert baseline.stage_metrics.mean_total_pipeline_latency_ms == 12.0
    assert hybrid.stage_metrics.mean_total_pipeline_latency_ms == 14.0
    assert baseline.stage_metrics.rerank_attempted_case_count == 0
    assert hybrid.stage_metrics.rerank_attempted_case_count == 0
    assert reranked.stage_metrics.rerank_attempted_case_count == 40
    assert reranked.stage_metrics.rerank_succeeded_case_count == 40
    assert reranked.stage_metrics.mean_rerank_latency_ms == 1.0
    assert reranked.stage_metrics.rerank_input_tokens == 8000
    assert reranked.stage_metrics.rerank_estimated_cost_cny == pytest.approx(0.0064)
    assert reranked.stage_metrics.total_tokens == 14000
    assert reranked.stage_metrics.total_estimated_cost_cny == pytest.approx(0.0464)
    assert reranked.stage_metrics.total_estimated_cost_complete is True


def test_comparison_report_rejects_tampered_fingerprint_and_duplicate_config() -> None:
    report = build_report()
    payload = report.model_dump(mode="json")
    payload["candidates"][0]["profile"]["configuration_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="配置指纹"):
        RagComparisonReport.model_validate(payload)

    duplicate = report.model_dump(mode="json")
    duplicate["candidates"][1]["profile"]["configuration"] = duplicate[
        "candidates"
    ][0]["profile"]["configuration"]
    duplicate["candidates"][1]["profile"]["configuration_fingerprint"] = duplicate[
        "candidates"
    ][0]["profile"]["configuration_fingerprint"]
    with pytest.raises(ValidationError, match="完整配置不能重复"):
        RagComparisonReport.model_validate(duplicate)

    wrong_total = report.model_dump(mode="json")
    wrong_total["candidates"][2]["stage_metrics"]["total_tokens"] += 1
    with pytest.raises(ValidationError, match="总Token"):
        RagComparisonReport.model_validate(wrong_total)


def test_checked_in_comparison_report_plan_and_schemas_are_reproducible() -> None:
    report = build_report()
    plan = build_plan()
    checked_report = json.loads(
        (EVALUATION_ROOT / "reports" / "rag_v1_2_mock_comparison_v1.json").read_text(
            encoding="utf-8"
        )
    )
    checked_plan = json.loads(
        (EVALUATION_ROOT / "plans" / "rag_v1_2_preflight_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_report == report.model_dump(mode="json")
    assert checked_plan == plan.model_dump(mode="json")
    assert RagComparisonReport.model_validate(checked_report) == report
    assert ComparisonRunPlan.model_validate(checked_plan) == plan
    assert json.loads(
        (
            EVALUATION_ROOT / "schemas" / "rag_comparison_report_v1.schema.json"
        ).read_text(encoding="utf-8")
    ) == RagComparisonReport.model_json_schema()
    assert json.loads(
        (
            EVALUATION_ROOT / "schemas" / "rag_comparison_plan_v1.schema.json"
        ).read_text(encoding="utf-8")
    ) == ComparisonRunPlan.model_json_schema()
    serialized = json.dumps(checked_report, ensure_ascii=False)
    assert '"question"' not in serialized
    assert '"answer_text"' not in serialized


def test_preflight_reuses_frozen_baseline_and_requires_paid_confirmation() -> None:
    plan = build_plan()

    assert plan.paid_execution_available is True
    assert plan.requires_new_user_confirmation is True
    assert plan.production_flags_changed is False
    assert plan.baseline_candidate_id == "vector_baseline_v1"
    assert plan.new_candidate_ids == ["hybrid_rrf_v1", "hybrid_rrf_rerank_v1"]
    assert plan.hard_limits.max_embedding_calls == 80
    assert plan.hard_limits.max_answer_calls == 80
    assert plan.hard_limits.max_rerank_calls == 40
    assert plan.hard_limits.automatic_retries == 0
    assert plan.hard_limits.max_total_tokens == 1_480_000
    assert plan.hard_limits.max_estimated_cost_cny == 4.4
    assert plan.pricing.expected_cost_min_cny == 0.6
    assert plan.pricing.expected_cost_max_cny == 1.0


def test_checked_in_real_comparison_is_frozen_valid_and_contains_no_body() -> None:
    path = EVALUATION_ROOT / "reports" / "rag_v1_2_real_comparison_v1.json"
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == (
        "f54e86a1b39518d998e861c101b225b160188d373488bca4fa821913c09e2893"
    )
    report = RagComparisonReport.model_validate_json(content)

    assert report.run_kind == "real_comparison"
    assert [item.profile.candidate_id for item in report.candidates] == [
        "vector_baseline_v1",
        "hybrid_rrf_v1",
        "hybrid_rrf_rerank_v1",
    ]
    assert all(item.evaluation_report.metrics.failed_case_count == 0 for item in report.candidates)
    assert report.candidates[1].stage_metrics.total_estimated_cost_cny == pytest.approx(0.286745)
    assert report.candidates[2].stage_metrics.total_estimated_cost_cny == pytest.approx(0.335861)
    serialized = content.decode("utf-8")
    assert '"question"' not in serialized
    assert '"answer_text"' not in serialized


def test_preflight_rejects_changed_frozen_report_before_any_run(tmp_path: Path) -> None:
    from scripts.preflight_rag_v1_2_comparison import (
        EVALUATION_ROOT as ROOT,
    )
    from scripts.run_mock_comparison import load_assets

    evaluation_set, corpus, categories = load_assets()
    changed = tmp_path / "current_baseline_v1.json"
    changed.write_bytes(
        (ROOT / "reports" / "current_baseline_v1.json").read_bytes() + b" "
    )

    with pytest.raises(ValueError, match="哈希不一致"):
        build_comparison_run_plan(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=categories,
            baseline_path=changed,
            human_capture_path=(
                ROOT / "reports" / "human_review_capture_v1.json"
            ),
        )
