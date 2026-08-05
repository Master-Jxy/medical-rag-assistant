import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.corpus_v2 import (
    CorpusV2Document,
    CorpusV2Manifest,
    CorpusV2PreflightSummary,
    EvaluationSetV2,
    ProviderCallBudget,
    build_cleaning_dedup_report,
    build_coverage_matrix,
    build_preflight_summary,
    calculate_corpus_v2_checksum,
    load_evaluation_set,
    load_manifest,
    validate_corpus_v2_assets,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"
MANIFEST_PATH = EVALUATION_ROOT / "corpora" / "corpus_v2_manifest.json"
DATASET_PATH = EVALUATION_ROOT / "datasets" / "eval_v2.json"


def load_assets() -> tuple[CorpusV2Manifest, EvaluationSetV2]:
    return load_manifest(MANIFEST_PATH), load_evaluation_set(DATASET_PATH)


def manifest_payload() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def evaluation_payload() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_checked_in_corpus_v2_assets_are_valid_and_do_not_overwrite_v1() -> None:
    manifest, evaluation_set = load_assets()

    summary = validate_corpus_v2_assets(manifest, evaluation_set)

    assert manifest.schema_version == "corpus_manifest_v2"
    assert manifest.corpus_version == "corpus_v2"
    assert manifest.prior_corpus_version == "corpus_v1"
    assert manifest.overwrite_policy == "never_overwrite_corpus_v1"
    assert manifest.document_count == 10
    assert summary.case_count == 9
    assert summary.blocked_case_count == 8
    assert manifest.corpus_checksum == calculate_corpus_v2_checksum(manifest.documents)
    assert all(document.content_sha256 == "unknown" for document in manifest.documents)
    assert all(document.ingestion_status != "ready" for document in manifest.documents)


def test_checked_in_corpus_v2_schemas_match_code_contracts() -> None:
    expected = {
        "corpus_v2_manifest.schema.json": CorpusV2Manifest.model_json_schema(),
        "evaluation_set_v2.schema.json": EvaluationSetV2.model_json_schema(),
        "corpus_v2_preflight_summary.schema.json": (
            CorpusV2PreflightSummary.model_json_schema()
        ),
    }

    for file_name, schema in expected.items():
        checked_in = json.loads(
            (EVALUATION_ROOT / "schemas" / file_name).read_text(encoding="utf-8")
        )
        assert checked_in == schema


def test_manifest_schema_rejects_bad_checksum_and_traversal() -> None:
    payload = manifest_payload()
    payload["corpus_checksum"] = "0" * 64
    with pytest.raises(ValidationError, match="corpus_checksum mismatch"):
        CorpusV2Manifest.model_validate(payload)

    document = manifest_payload()["documents"][0]
    document["relative_path"] = "../private.pdf"
    with pytest.raises(ValidationError, match="relative_path"):
        CorpusV2Document.model_validate(document)


def test_validation_rejects_duplicate_document_id() -> None:
    payload = manifest_payload()
    payload["documents"][1]["id"] = payload["documents"][0]["id"]
    documents = [CorpusV2Document.model_validate(item) for item in payload["documents"]]
    payload["corpus_checksum"] = calculate_corpus_v2_checksum(documents)
    manifest = CorpusV2Manifest.model_validate(payload)
    evaluation_set = EvaluationSetV2.model_validate(evaluation_payload())

    with pytest.raises(ValueError, match="duplicate document id"):
        validate_corpus_v2_assets(manifest, evaluation_set)


def test_validation_rejects_missing_evaluation_reference() -> None:
    manifest, _ = load_assets()
    payload = evaluation_payload()
    payload["cases"][0]["expected_source_document_ids"].append("cv2_missing_doc")
    payload["cases"][0]["expected_evidence"].append(
        {
            "document_id": "cv2_missing_doc",
            "evidence_key": "missing",
            "note": "should fail",
        }
    )
    evaluation_set = EvaluationSetV2.model_validate(payload)

    with pytest.raises(ValueError, match="references unknown documents"):
        validate_corpus_v2_assets(manifest, evaluation_set)


def test_unknown_license_and_blocked_cases_are_reported_without_provider_calls() -> None:
    manifest, evaluation_set = load_assets()

    validation = validate_corpus_v2_assets(manifest, evaluation_set)
    coverage = build_coverage_matrix(manifest, evaluation_set)
    preflight = build_preflight_summary(manifest, evaluation_set, coverage)

    assert any("license unknown" in warning for warning in validation.warnings)
    assert any("eval2_004: blocked" in warning for warning in validation.warnings)
    assert preflight.no_cost_gate_passed is True
    assert preflight.provider_calls.model_dump() == {
        "embedding_calls": 0,
        "llm_calls": 0,
        "rerank_calls": 0,
        "ocr_calls": 0,
        "vision_calls": 0,
    }
    assert preflight.would_require_provider_calls_after_approval.embedding_calls > 0
    assert preflight.would_require_provider_calls_after_approval.ocr_calls > 0
    assert preflight.would_require_provider_calls_after_approval.vision_calls > 0


def test_no_cost_gate_fails_for_any_current_provider_call() -> None:
    manifest, evaluation_set = load_assets()
    coverage = build_coverage_matrix(manifest, evaluation_set)

    preflight = build_preflight_summary(
        manifest,
        evaluation_set,
        coverage,
        provider_calls=ProviderCallBudget(embedding_calls=1),
    )
    executing_preflight = build_preflight_summary(
        manifest,
        evaluation_set,
        coverage,
        execute_provider_calls=True,
    )

    assert preflight.no_cost_gate_passed is False
    assert executing_preflight.no_cost_gate_passed is False


def test_provider_dependent_cases_must_remain_blocked() -> None:
    payload = evaluation_payload()["cases"][4]
    payload["expected_behavior"] = "answer"
    payload["blocked_reason"] = None

    with pytest.raises(ValidationError, match="provider-dependent cases"):
        EvaluationSetV2.model_validate(
            {
                "schema_version": "evaluation_set_v2",
                "dataset_version": "eval_v2",
                "corpus_version": "corpus_v2",
                "corpus_checksum": "a" * 64,
                "cases": [payload],
            }
        )


def test_coverage_matrix_records_current_gaps() -> None:
    manifest, evaluation_set = load_assets()

    coverage = build_coverage_matrix(manifest, evaluation_set)

    assert coverage.gaps == [
        "basic_fact",
        "multi_source",
        "table",
        "scan_ocr",
        "image_vision",
        "refusal",
        "version_conflict",
        "duplicate",
        "multi_format",
        "web_snapshot",
    ]
    by_id = {item.id: item for item in coverage.items}
    assert by_id["multi_format"].planned_count == 10
    assert by_id["multi_format"].current_count == 0
    assert by_id["multi_format"].blocked_count == 10
    assert by_id["multi_format"].gap == 4
    assert by_id["multi_format"].evidence_document_ids == []
    assert len(by_id["multi_format"].planned_document_ids) == 10
    assert by_id["web_snapshot"].planned_count == 1
    assert by_id["web_snapshot"].current_count == 0
    assert by_id["web_snapshot"].gap == 1
    assert by_id["multi_source"].planned_count == 2
    assert by_id["multi_source"].current_count == 0
    assert by_id["multi_source"].blocked_count == 2
    assert by_id["refusal"].planned_count == 1
    assert by_id["refusal"].current_count == 1
    assert by_id["refusal"].executable_case_ids == ["eval2_006"]


def test_dedup_report_is_deterministic_metadata_only_and_does_not_delete() -> None:
    manifest, _ = load_assets()

    first = build_cleaning_dedup_report(manifest)
    second = build_cleaning_dedup_report(manifest)

    assert first == second
    assert first.generated_from == "manifest_metadata_only"
    assert first.auto_deleted is False
    assert first.exact_duplicate_groups == []
    assert first.normalized_duplicate_groups == []
    assert first.near_duplicate_hints == []
    assert set(first.skipped_unknown_content_ids) == {
        document.id for document in manifest.documents
    }
    checked_in = json.loads(
        (EVALUATION_ROOT / "corpora" / "corpus_v2_cleaning_dedup_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_in == first.model_dump(mode="json")
