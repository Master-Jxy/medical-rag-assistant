import json
from pathlib import Path

import pytest

from app.evaluation.fake_adapters import (
    FixedFakeAnswerAdapter,
    FixedFakeRetrievalAdapter,
)
from app.evaluation.report_schemas import BaselineReport
from app.evaluation.runner import calculate_evaluation_checksum, run_evaluation
from app.evaluation.schemas import CorpusManifest, EvaluationSet, ExpectedBehavior
from app.evaluation.validation import EvaluationValidationError
from scripts.run_fake_evaluation import build_fake_dry_run

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"


def load_assets() -> tuple[EvaluationSet, CorpusManifest, dict]:
    evaluation_set = EvaluationSet.model_validate_json(
        (EVALUATION_ROOT / "datasets" / "eval_v1.json").read_text(
            encoding="utf-8"
        )
    )
    corpus = CorpusManifest.model_validate_json(
        (EVALUATION_ROOT / "corpora" / "corpus_v1.json").read_text(
            encoding="utf-8"
        )
    )
    categories = json.loads(
        (EVALUATION_ROOT / "categories_v1.json").read_text(encoding="utf-8")
    )
    return evaluation_set, corpus, categories


def run_with_fakes(
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    categories: dict,
    retrieval: FixedFakeRetrievalAdapter,
    answer: FixedFakeAnswerAdapter,
) -> BaselineReport:
    return run_evaluation(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=categories,
        retrieval_port=retrieval,
        answer_port=answer,
        report_version="test_run_v1",
        run_kind="fake_dry_run",
    )


def test_fake_dry_run_covers_failures_and_missing_usage() -> None:
    report = build_fake_dry_run()
    metrics = report.metrics
    evaluation_set, corpus, _ = load_assets()

    assert report.corpus_checksum == corpus.corpus_checksum
    assert report.corpus_checksum == evaluation_set.corpus_checksum
    assert report.evaluation_checksum == calculate_evaluation_checksum(evaluation_set)
    assert metrics.case_count == 40
    assert metrics.completed_case_count == 38
    assert metrics.failed_case_count == 2
    assert metrics.source_scored_case_count == 28
    assert metrics.mean_source_recall == 1.0
    assert metrics.full_source_hit_rate == 1.0
    assert metrics.behavior_accuracy == 1.0
    assert metrics.refusal_scored_case_count == 10
    assert metrics.refusal_accuracy == 1.0
    assert metrics.mean_key_fact_coverage == 1.0
    assert metrics.retrieval_observed_case_count == 39
    assert metrics.answer_observed_case_count == 38
    assert metrics.usage_reported_case_count == 37
    assert metrics.usage_missing_case_count == 1
    assert metrics.total_tokens == 5550
    assert metrics.estimated_cost_cny == pytest.approx(0.037)
    assert metrics.estimated_cost_complete is False
    assert report.scoring_methods.key_fact == "normalized_exact_substring_v1"

    by_id = {result.case_id: result for result in report.cases}
    assert by_id["eval_036"].status == "completed"
    assert by_id["eval_036"].usage is None
    assert by_id["eval_039"].error_stage == "retrieval"
    assert by_id["eval_039"].error_type == "FakeRetrievalError"
    assert by_id["eval_040"].error_stage == "answer"
    assert by_id["eval_040"].error_type == "FakeAnswerError"


def test_checked_in_report_and_schema_match_reproducible_output() -> None:
    checked_in = json.loads(
        (EVALUATION_ROOT / "reports" / "dry_run_v1.json").read_text(
            encoding="utf-8"
        )
    )
    report = build_fake_dry_run()
    assert checked_in == report.model_dump(mode="json")
    assert BaselineReport.model_validate(checked_in) == report

    schema = json.loads(
        (EVALUATION_ROOT / "schemas" / "baseline_report_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema == BaselineReport.model_json_schema()
    rendered = json.dumps(checked_in, ensure_ascii=False)
    assert '"question"' not in rendered
    assert '"answer_text"' not in rendered


def test_runner_scores_partial_sources_facts_and_wrong_refusal() -> None:
    evaluation_set, corpus, categories = load_assets()
    multi_case = evaluation_set.cases[14]
    refusal_case = evaluation_set.cases[28]
    retrieval = FixedFakeRetrievalAdapter(
        evaluation_set,
        source_overrides={
            multi_case.case_id: (multi_case.expected_source_document_ids[0],)
        },
    )
    answer = FixedFakeAnswerAdapter(
        evaluation_set,
        answer_text_overrides={
            multi_case.case_id: multi_case.expected_key_facts[0]
        },
        behavior_overrides={refusal_case.case_id: ExpectedBehavior.ANSWER},
    )

    report = run_with_fakes(
        evaluation_set, corpus, categories, retrieval, answer
    )
    by_id = {result.case_id: result for result in report.cases}

    assert by_id[multi_case.case_id].source_recall == 0.25
    assert by_id[multi_case.case_id].source_full_hit is False
    assert by_id[multi_case.case_id].key_fact_coverage == pytest.approx(1 / 3)
    assert by_id[refusal_case.case_id].behavior_correct is False
    assert report.metrics.full_source_hit_rate == pytest.approx(27 / 28, abs=1e-6)
    assert report.metrics.refusal_accuracy == pytest.approx(11 / 12, abs=1e-6)


def test_answer_failure_preserves_completed_retrieval_score() -> None:
    evaluation_set, corpus, categories = load_assets()
    failed_case = evaluation_set.cases[0]
    retrieval = FixedFakeRetrievalAdapter(evaluation_set)
    answer = FixedFakeAnswerAdapter(
        evaluation_set, failure_case_ids={failed_case.case_id}
    )

    report = run_with_fakes(
        evaluation_set, corpus, categories, retrieval, answer
    )
    result = next(item for item in report.cases if item.case_id == failed_case.case_id)

    assert result.status == "failed"
    assert result.error_stage == "answer"
    assert result.source_recall == 1.0
    assert result.source_full_hit is True
    assert report.metrics.source_scored_case_count == 28
    assert report.metrics.mean_source_recall == 1.0


def test_checksum_mismatch_fails_before_any_adapter_call() -> None:
    evaluation_set, corpus, categories = load_assets()
    invalid = evaluation_set.model_copy(deep=True)
    invalid.corpus_checksum = "0" * 64

    class NeverRetrieval:
        adapter_name = "never_retrieval"

        def retrieve(self, query):
            raise AssertionError("checksum 失败后不应调用检索")

    class NeverAnswer:
        adapter_name = "never_answer"

        def answer(self, query, source_document_ids):
            raise AssertionError("checksum 失败后不应调用回答")

    with pytest.raises(
        EvaluationValidationError, match="corpus_checksum 与语料清单不一致"
    ):
        run_evaluation(
            evaluation_set=invalid,
            corpus=corpus,
            category_config=categories,
            retrieval_port=NeverRetrieval(),
            answer_port=NeverAnswer(),
            report_version="test_run_v1",
            run_kind="fake_dry_run",
        )
