import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.quality import router as quality_router
from app.core.exceptions import register_exception_handlers
from app.evaluation.admin_summary import (
    CorpusEvaluationPublicSummary,
    build_public_summary,
)
from app.evaluation.corpus_v2 import (
    CorpusV2Manifest,
    CorpusV2PreflightReport,
    EvaluationSetV2,
    load_evaluation_set,
    load_manifest,
    preflight_corpus_v2,
)
from app.evaluation.eval_v2 import (
    EvalV2CandidatePolicy,
    EvalV2Report,
    FakeEvalV2AnswerAdapter,
    FakeEvalV2RetrievalAdapter,
    run_eval_v2,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"


def _assets() -> tuple[CorpusV2Manifest, EvaluationSetV2]:
    return (
        load_manifest(EVALUATION_ROOT / "corpora" / "corpus_v2_manifest.json"),
        load_evaluation_set(EVALUATION_ROOT / "datasets" / "eval_v2.json"),
    )


def _user(role: str) -> UserResponse:
    now = datetime.now(timezone.utc)
    return UserResponse(
        id=f"{role}-1",
        email=f"{role}@example.com",
        display_name=role,
        is_active=True,
        role=role,
        created_at=now,
        updated_at=now,
    )


def test_current_corpus_is_not_eligible_and_makes_zero_fake_or_provider_calls() -> None:
    manifest, evaluation_set = _assets()
    retrieval = FakeEvalV2RetrievalAdapter()
    answer = FakeEvalV2AnswerAdapter()

    preflight = preflight_corpus_v2(
        manifest,
        evaluation_set,
        asset_root=EVALUATION_ROOT,
    )
    report = run_eval_v2(
        manifest=manifest,
        evaluation_set=evaluation_set,
        asset_root=EVALUATION_ROOT,
        retrieval_port=retrieval,
        answer_port=answer,
        generated_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )

    assert preflight.status == "not_eligible"
    assert preflight.human_golden_case_count == 0
    assert {item.code for item in preflight.issues} >= {
        "human_golden_missing",
        "license_not_approved",
        "missing_file",
        "missing_content_hash",
    }
    assert retrieval.calls == 0
    assert answer.calls == 0
    assert report.no_cost_gate_passed is True
    assert not any(report.provider_calls.model_dump().values())
    assert report.candidate_policy == EvalV2CandidatePolicy(
        candidate_pool_size=16,
        max_chunks_per_document=2,
        final_top_k=4,
    )
    assert report.promotion.decision == "not_eligible"


def test_stage26_eval_v2_schemas_and_report_are_reproducible() -> None:
    expected = {
        "corpus_v2_strict_preflight.schema.json": (
            CorpusV2PreflightReport.model_json_schema()
        ),
        "eval_v2_report.schema.json": EvalV2Report.model_json_schema(),
        "corpus_evaluation_public_summary.schema.json": (
            CorpusEvaluationPublicSummary.model_json_schema()
        ),
    }
    for name, schema in expected.items():
        checked = json.loads(
            (EVALUATION_ROOT / "schemas" / name).read_text(encoding="utf-8")
        )
        assert checked == schema

    manifest, evaluation_set = _assets()
    report = run_eval_v2(
        manifest=manifest,
        evaluation_set=evaluation_set,
        asset_root=EVALUATION_ROOT,
        generated_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    checked_report = json.loads(
        (EVALUATION_ROOT / "reports" / "eval_v2_fake_latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_report == report.model_dump(mode="json")


def test_admin_evaluation_summary_is_role_protected_and_redacted() -> None:
    application = FastAPI()
    application.include_router(quality_router, prefix="/api/v1")
    register_exception_handlers(application)
    application.dependency_overrides[get_current_user] = lambda: _user("user")
    with TestClient(application, raise_server_exceptions=False) as client:
        forbidden = client.get("/api/v1/admin/quality/evaluation-summary")
    assert forbidden.status_code == 403

    application.dependency_overrides[get_current_user] = lambda: _user("admin")
    with TestClient(application) as client:
        allowed = client.get("/api/v1/admin/quality/evaluation-summary")
    application.dependency_overrides.clear()

    assert allowed.status_code == 200
    body = allowed.json()
    assert body["preflight_status"] == "not_eligible"
    assert body["promotion_decision"] == "not_eligible"
    rendered = json.dumps(body, ensure_ascii=False).casefold()
    for forbidden_key in (
        "source_url",
        "relative_path",
        "file_name",
        "question",
        "answer_text",
    ):
        assert forbidden_key not in rendered
    assert build_public_summary(EVALUATION_ROOT).document_count == 10
