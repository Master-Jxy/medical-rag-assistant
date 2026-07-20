import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.evaluation.human_review import (
    HumanReviewDecisionSet,
    HumanBehaviorDecision,
    HumanFactDecision,
    LocalHumanReviewBundle,
    LocalHumanReviewItem,
    apply_human_review_decisions,
    sha256_file,
    validate_and_compare_human_review,
)
from app.evaluation.review_scoring import (
    AliasKeyFactRubric,
    BASELINE_V1_INSUFFICIENT_MESSAGE,
    RefusalReviewClassification,
    classify_refusal_v1,
    classify_refusal_v2,
    exact_key_fact_coverage_v1,
    score_alias_key_fact_v2,
)
from app.evaluation.review_capture import (
    RecordingAnswerAdapter,
    build_initial_review_bundle,
    capture_temporary_path,
    cleanup_capture_temporary_files,
    publish_capture_artifacts,
    write_local_review_bundle,
)
from app.evaluation.ports import AnswerObservation, EvaluationQuery
from app.evaluation.schemas import EvaluationSet
from app.evaluation.schemas import ExpectedBehavior
from app.evaluation.report_schemas import BaselineReport
from app.services.rag_service import INSUFFICIENT_KNOWLEDGE_MESSAGE

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"
REPORT = EVALUATION_ROOT / "reports" / "current_baseline_v1.json"
CAPTURE_REPORT = EVALUATION_ROOT / "reports" / "human_review_capture_v1.json"
DECISIONS = EVALUATION_ROOT / "reviews" / "human_review_capture_v1_decisions.json"
DATASET = EVALUATION_ROOT / "datasets" / "eval_v1.json"
REPORT_SHA256 = "598952a8772fde26eac428cdad0335f889241f61d12b9c55bfabed5329a26ed5"


def load_dataset() -> EvaluationSet:
    return EvaluationSet.model_validate_json(DATASET.read_text(encoding="utf-8"))


def test_current_baseline_report_is_preserved_byte_for_byte() -> None:
    assert sha256_file(REPORT) == REPORT_SHA256
    assert BASELINE_V1_INSUFFICIENT_MESSAGE == INSUFFICIENT_KNOWLEDGE_MESSAGE


def test_alternative_refusal_wording_is_exposed_without_changing_v1() -> None:
    answer = "我不能保证在家等待是安全的，请马上联系急救人员。"

    assert classify_refusal_v1(answer) == RefusalReviewClassification.ANSWER
    assert classify_refusal_v2(answer) == RefusalReviewClassification.REFUSE


def test_soft_boundary_wording_stays_for_human_review() -> None:
    answer = "抗凝药不能自行停用，应由医生结合手术风险制定方案。"

    assert classify_refusal_v2(answer) == RefusalReviewClassification.NEEDS_REVIEW


def test_human_alias_rubric_recognizes_paraphrase_and_flags_contradiction() -> None:
    fact = "出现危险胸痛时应立即拨打120，并且不要自行驾车。"
    paraphrase = "请马上呼叫急救，不要自己开车去医院。"
    rubric = AliasKeyFactRubric(
        concept_alias_groups=(
            ("立即拨打120", "马上呼叫急救", "联系120"),
            ("不要自行驾车", "不要自己开车", "不能自己开车"),
        ),
        contradiction_phrases=("可以在家观察", "可以自己开车去医院"),
    )

    assert exact_key_fact_coverage_v1(paraphrase, (fact,)) == 0.0
    score = score_alias_key_fact_v2(paraphrase, rubric)
    assert score.coverage == 1.0
    assert score.contradiction_found is False
    assert score.needs_review is False

    contradictory = score_alias_key_fact_v2(
        paraphrase + "如果不舒服也可以在家观察。", rubric
    )
    assert contradictory.coverage == 1.0
    assert contradictory.contradiction_found is True
    assert contradictory.needs_review is True


def build_bundle(
    evaluation_set: EvaluationSet,
    *,
    created_at: datetime,
    expires_at: datetime,
    report_hash: str = REPORT_SHA256,
) -> LocalHumanReviewBundle:
    selected = [evaluation_set.cases[0], evaluation_set.cases[36]]
    return LocalHumanReviewBundle(
        schema_version="local_human_review_v1",
        dataset_version=evaluation_set.dataset_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        source_report_sha256=report_hash,
        created_at=created_at,
        expires_at=expires_at,
        items=[
            LocalHumanReviewItem(
                case_id=case.case_id,
                answer_text="这是固定脱敏样例，不是真实模型回答。",
                behavior_decision=(
                    HumanBehaviorDecision.ANSWER
                    if case.case_id == "eval_001"
                    else HumanBehaviorDecision.REFUSE
                ),
                key_fact_decisions=[HumanFactDecision.MET] * len(case.expected_key_facts),
                reviewer_notes="固定测试标注",
            )
            for case in selected
        ],
    )


def test_local_human_review_compares_with_original_without_answer_leak() -> None:
    evaluation_set = load_dataset()
    created_at = datetime(2026, 7, 18, 18, tzinfo=timezone.utc)
    bundle = build_bundle(
        evaluation_set,
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
    )

    comparison = validate_and_compare_human_review(
        bundle=bundle,
        evaluation_set=evaluation_set,
        report_path=REPORT,
        now=created_at + timedelta(days=1),
    )

    assert comparison.reviewed_case_count == 2
    assert comparison.original_behavior_accuracy == 0.5
    assert comparison.human_behavior_accuracy == 1.0
    assert comparison.original_mean_key_fact_coverage == 0.0
    assert comparison.human_mean_key_fact_coverage == 1.0
    rendered = json.dumps(comparison.__dict__, ensure_ascii=False)
    assert "固定脱敏样例" not in rendered
    assert "reviewer_notes" not in rendered


def test_local_review_rejects_expiry_hash_mismatch_and_long_retention() -> None:
    evaluation_set = load_dataset()
    created_at = datetime(2026, 7, 18, 18, tzinfo=timezone.utc)
    expired = build_bundle(
        evaluation_set,
        created_at=created_at,
        expires_at=created_at + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="已过期"):
        validate_and_compare_human_review(
            bundle=expired,
            evaluation_set=evaluation_set,
            report_path=REPORT,
            now=created_at + timedelta(days=2),
        )

    wrong_hash = build_bundle(
        evaluation_set,
        created_at=created_at,
        expires_at=created_at + timedelta(days=1),
        report_hash="0" * 64,
    )
    with pytest.raises(ValueError, match="报告哈希不一致"):
        validate_and_compare_human_review(
            bundle=wrong_hash,
            evaluation_set=evaluation_set,
            report_path=REPORT,
            now=created_at,
        )

    with pytest.raises(ValidationError, match="最多保留7天"):
        build_bundle(
            evaluation_set,
            created_at=created_at,
            expires_at=created_at + timedelta(days=8),
        )


def test_review_code_has_no_database_or_model_dependency() -> None:
    import app.evaluation.human_review as human_review
    import app.evaluation.review_scoring as review_scoring

    source = inspect.getsource(human_review) + inspect.getsource(review_scoring)
    forbidden = ("app.db", "sqlalchemy", "ChatTongyi", "DashScope", "Chroma")
    assert all(value not in source for value in forbidden)


def test_local_review_directory_is_git_ignored() -> None:
    gitignore = (BACKEND_DIR.parent / ".gitignore").read_text(encoding="utf-8")
    assert "backend/evaluation/local_reviews/" in gitignore


def test_recording_adapter_delegates_once_and_keeps_answer_only_in_memory() -> None:
    wrapped = Mock()
    wrapped.adapter_name = "fixed_answer"
    wrapped.answer.return_value = AnswerObservation(
        behavior=ExpectedBehavior.ANSWER,
        answer_text="固定脱敏回答",
        latency_ms=1.0,
        usage=None,
    )
    adapter = RecordingAnswerAdapter(wrapped)
    query = EvaluationQuery("eval_001", "固定问题", ())

    result = adapter.answer(query, ("doc-1",))

    wrapped.answer.assert_called_once_with(query, ("doc-1",))
    assert result.answer_text == "固定脱敏回答"
    assert adapter.answers == {"eval_001": "固定脱敏回答"}


def test_capture_builds_seven_day_uncertain_bundle_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    evaluation_set = load_dataset()
    report_copy = tmp_path / "report.json"
    report_copy.write_bytes(REPORT.read_bytes())
    answers = {
        case.case_id: f"{case.case_id} 固定脱敏回答"
        for case in evaluation_set.cases
    }
    created_at = datetime(2026, 7, 18, 18, tzinfo=timezone.utc)
    bundle = build_initial_review_bundle(
        evaluation_set=evaluation_set,
        report_path=report_copy,
        answers=answers,
        created_at=created_at,
    )

    assert bundle.expires_at == created_at + timedelta(days=7)
    assert len(bundle.items) == 40
    assert all(
        item.behavior_decision == HumanBehaviorDecision.UNCERTAIN
        for item in bundle.items
    )
    assert bundle.source_report_sha256 == REPORT_SHA256

    root = tmp_path / "local_reviews"
    output = root / "capture.json"
    write_local_review_bundle(
        bundle=bundle, output_path=output, local_review_root=root
    )
    loaded = LocalHumanReviewBundle.model_validate_json(
        output.read_text(encoding="utf-8")
    )
    assert loaded == bundle
    with pytest.raises(FileExistsError, match="禁止覆盖"):
        write_local_review_bundle(
            bundle=bundle, output_path=output, local_review_root=root
        )
    with pytest.raises(ValueError, match="受控 local_reviews"):
        write_local_review_bundle(
            bundle=bundle,
            output_path=tmp_path / "outside.json",
            local_review_root=root,
        )


def test_capture_rejects_incomplete_answer_set(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="回答捕获不完整"):
        build_initial_review_bundle(
            evaluation_set=load_dataset(),
            report_path=REPORT,
            answers={"eval_001": "只有一个回答"},
        )


def test_capture_publish_failure_on_second_replace_leaves_no_formal_artifact(
    tmp_path: Path,
) -> None:
    evaluation_set = load_dataset()
    report = BaselineReport.model_validate_json(REPORT.read_text(encoding="utf-8"))
    report_output = tmp_path / "reports" / "capture.json"
    local_root = tmp_path / "local_reviews"
    local_output = local_root / "capture.json"
    answers = {
        case.case_id: f"{case.case_id} 固定脱敏回答"
        for case in evaluation_set.cases
    }
    replacements = 0

    def fail_second_replace(source: Path, target: Path) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("模拟第二份文件发布失败")
        source.replace(target)

    with pytest.raises(OSError, match="第二份文件发布失败"):
        publish_capture_artifacts(
            report=report,
            evaluation_set=evaluation_set,
            answers=answers,
            report_output=report_output,
            local_review_output=local_output,
            local_review_root=local_root,
            replace_file=fail_second_replace,
        )

    assert not report_output.exists()
    assert not local_output.exists()
    assert not capture_temporary_path(report_output).exists()
    assert not capture_temporary_path(local_output).exists()


def test_capture_second_staged_write_failure_leaves_no_formal_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluation_set = load_dataset()
    report = BaselineReport.model_validate_json(REPORT.read_text(encoding="utf-8"))
    report_output = tmp_path / "reports" / "capture.json"
    local_root = tmp_path / "local_reviews"
    local_output = local_root / "capture.json"
    local_temporary = capture_temporary_path(local_output.resolve())
    original_write_text = Path.write_text

    def fail_local_staged_write(path: Path, data: str, **kwargs) -> int:
        if path == local_temporary:
            raise OSError("模拟第二份暂存文件写入失败")
        return original_write_text(path, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_local_staged_write)
    with pytest.raises(OSError, match="第二份暂存文件写入失败"):
        publish_capture_artifacts(
            report=report,
            evaluation_set=evaluation_set,
            answers={
                case.case_id: f"{case.case_id} 固定脱敏回答"
                for case in evaluation_set.cases
            },
            report_output=report_output,
            local_review_output=local_output,
            local_review_root=local_root,
        )

    assert not report_output.exists()
    assert not local_output.exists()
    assert not capture_temporary_path(report_output).exists()
    assert not capture_temporary_path(local_output).exists()


def test_capture_cleanup_removes_only_stale_temporary_files(tmp_path: Path) -> None:
    report_output = tmp_path / "report.json"
    local_output = tmp_path / "local.json"
    report_output.write_text("formal", encoding="utf-8")
    report_temporary = capture_temporary_path(report_output)
    local_temporary = capture_temporary_path(local_output)
    report_temporary.write_text("stale", encoding="utf-8")
    local_temporary.write_text("stale", encoding="utf-8")

    cleanup_capture_temporary_files(report_output, local_output)

    assert report_output.read_text(encoding="utf-8") == "formal"
    assert not report_temporary.exists()
    assert not local_temporary.exists()


def test_sanitized_decisions_cover_capture_report_without_answer_text() -> None:
    evaluation_set = load_dataset()
    decisions_text = DECISIONS.read_text(encoding="utf-8")
    decisions = HumanReviewDecisionSet.model_validate_json(decisions_text)
    assert '"answer_text"' not in decisions_text
    assert decisions.source_report_sha256 == sha256_file(CAPTURE_REPORT)
    assert {item.case_id for item in decisions.items} == {
        case.case_id for case in evaluation_set.cases
    }

    bundle = build_initial_review_bundle(
        evaluation_set=evaluation_set,
        report_path=CAPTURE_REPORT,
        answers={case.case_id: "固定脱敏回答" for case in evaluation_set.cases},
        created_at=datetime(2026, 7, 18, 18, tzinfo=timezone.utc),
    )
    updated = apply_human_review_decisions(
        bundle=bundle,
        decisions=decisions,
        evaluation_set=evaluation_set,
    )
    comparison = validate_and_compare_human_review(
        bundle=updated,
        evaluation_set=evaluation_set,
        report_path=CAPTURE_REPORT,
        now=datetime(2026, 7, 19, 18, tzinfo=timezone.utc),
    )
    assert comparison.reviewed_case_count == 40
    assert comparison.human_behavior_accuracy == 1.0
    assert comparison.human_mean_key_fact_coverage is not None
    assert comparison.human_mean_key_fact_coverage > 0.8
    assert comparison.fact_uncertain_count == 4
