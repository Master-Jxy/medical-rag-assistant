import json
from pathlib import Path

import pytest

from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.evaluation.validation import (
    EvaluationValidationError,
    validate_evaluation_set,
)

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


def test_eval_v1_passes_static_validation_and_covers_entire_corpus() -> None:
    evaluation_set, corpus, categories = load_assets()

    summary = validate_evaluation_set(evaluation_set, corpus, categories)

    assert summary.case_count == 40
    assert evaluation_set.corpus_checksum == corpus.corpus_checksum
    assert summary.category_counts == {
        "single_document": 14,
        "multi_document": 8,
        "conversational_follow_up": 6,
        "insufficient_knowledge": 8,
        "safety_boundary": 4,
    }
    assert summary.referenced_document_count == 27
    assert summary.unreferenced_document_ids == ()
    assert len({case.question for case in evaluation_set.cases}) == 40


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("duplicate_case_id", "case_id 重复"),
        ("duplicate_question", "问题文本重复"),
        ("unknown_source", "不存在的来源"),
        ("multi_one_source", "至少需要两个预期来源"),
        ("follow_up_without_history", "必须提供历史对话"),
        ("refusal_with_source", "不得登记伪造来源"),
        ("answer_without_evidence", "回答题，必须登记来源"),
        ("checksum_mismatch", "corpus_checksum 与语料清单不一致"),
    ],
)
def test_static_validation_rejects_invalid_dataset(
    mutation: str, expected_error: str
) -> None:
    evaluation_set, corpus, categories = load_assets()
    invalid = evaluation_set.model_copy(deep=True)

    if mutation == "duplicate_case_id":
        invalid.cases[1].case_id = invalid.cases[0].case_id
    elif mutation == "duplicate_question":
        invalid.cases[1].question = f"  {invalid.cases[0].question}  "
    elif mutation == "unknown_source":
        invalid.cases[0].expected_source_document_ids = ["missing-document"]
    elif mutation == "multi_one_source":
        invalid.cases[14].expected_source_document_ids = [
            invalid.cases[14].expected_source_document_ids[0]
        ]
    elif mutation == "follow_up_without_history":
        invalid.cases[22].history = []
    elif mutation == "refusal_with_source":
        invalid.cases[28].expected_source_document_ids = [corpus.documents[0].document_id]
    elif mutation == "answer_without_evidence":
        invalid.cases[0].expected_source_document_ids = []
        invalid.cases[0].expected_key_facts = []
    elif mutation == "checksum_mismatch":
        invalid.corpus_checksum = "0" * 64

    with pytest.raises(EvaluationValidationError, match=expected_error):
        validate_evaluation_set(invalid, corpus, categories)


def test_human_review_lists_every_case_and_uses_corpus_file_names() -> None:
    evaluation_set, corpus, _ = load_assets()
    review = (EVALUATION_ROOT / "reviews" / "eval_v1_review.md").read_text(
        encoding="utf-8"
    )

    assert review.count("| eval_") == 40
    for case in evaluation_set.cases:
        assert review.count(f"| {case.case_id} |") == 1
    for document in corpus.documents:
        assert document.original_name in review
    assert "来源覆盖：27/27" in review
    assert evaluation_set.corpus_checksum in review
