import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.retrieval_ranking import (
    build_retrieval_ranking_profiles,
    calculate_retrieval_ranking_metrics,
)
from app.evaluation.retrieval_ranking_schemas import RetrievalRankingReport
from app.modules.rag.ports import RetrievedChunk
from scripts.run_mock_retrieval_ranking import build_report

BACKEND_DIR = Path(__file__).resolve().parents[1]
EVALUATION_ROOT = BACKEND_DIR / "evaluation"


def chunk(index: int, document_id: str | None) -> RetrievedChunk:
    return RetrievedChunk(
        content=f"不会进入报告的正文{index}",
        file_name=f"资料{index}.txt",
        page=index,
        chunk_id=f"chunk-{index}",
        document_id=document_id,
    )


def test_document_metrics_handle_duplicates_and_exact_arithmetic() -> None:
    ranked = tuple(
        [
            chunk(1, "doc-a"),
            chunk(2, "doc-a"),
            chunk(3, "doc-b"),
            chunk(4, "doc-c"),
            chunk(5, "doc-d"),
            chunk(6, "doc-e"),
        ]
    )
    metrics, ranked_ids, final_ids = calculate_retrieval_ranking_metrics(
        expected_source_document_ids=["doc-a", "doc-c", "doc-e"],
        ranked_candidates=ranked,
        final_chunks=ranked[:4],
    )

    assert metrics.source_recall_at_4 == pytest.approx(2 / 3, abs=0.000001)
    assert metrics.source_recall_at_10 == 1.0
    assert metrics.full_source_hit_at_4 is False
    assert metrics.full_source_hit_at_10 is True
    assert metrics.mrr_at_4 == 1.0
    assert metrics.ndcg_at_4 == pytest.approx(0.703918, abs=0.000001)
    assert metrics.unique_document_count_at_4 == 3
    assert metrics.duplicate_chunk_ratio_at_4 == 0.25
    assert ranked_ids == ["doc-a", "doc-b", "doc-c", "doc-d", "doc-e"]
    assert final_ids == ["doc-a", "doc-a", "doc-b", "doc-c"]


def test_empty_expected_sources_are_excluded_and_unknown_ids_stay_distinct() -> None:
    ranked = tuple([chunk(1, None), chunk(2, None)])

    metrics, ranked_ids, final_ids = calculate_retrieval_ranking_metrics(
        expected_source_document_ids=[],
        ranked_candidates=ranked,
        final_chunks=ranked,
    )

    assert all(value is None for value in metrics.model_dump().values())
    assert ranked_ids == ["unknown:1", "unknown:2"]
    assert final_ids == ["unknown:1", "unknown:2"]


def test_four_profiles_have_fixed_bounds_and_unique_fingerprints() -> None:
    profiles = build_retrieval_ranking_profiles()

    assert [item.candidate_id for item in profiles] == [
        "vector_top4_reference",
        "vector_wide_diverse_v1",
        "hybrid_wide_diverse_v1",
        "hybrid_wide_diverse_rerank_v1",
    ]
    assert len({item.configuration_fingerprint for item in profiles}) == 4
    assert all(item.configuration.candidate_pool_size == 12 for item in profiles)
    assert all(item.configuration.max_chunks_per_document == 2 for item in profiles)
    assert all(item.configuration.final_top_k == 4 for item in profiles)


def test_profile_and_report_reject_tampering_or_duplicate_configuration() -> None:
    report = build_report()
    payload = report.model_dump(mode="json")
    payload["candidates"][0]["profile"]["configuration_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="配置指纹"):
        RetrievalRankingReport.model_validate(payload)

    duplicate = report.model_dump(mode="json")
    duplicate["candidates"][1]["profile"]["configuration"] = duplicate[
        "candidates"
    ][0]["profile"]["configuration"]
    duplicate["candidates"][1]["profile"]["configuration_fingerprint"] = duplicate[
        "candidates"
    ][0]["profile"]["configuration_fingerprint"]
    with pytest.raises(ValidationError, match="完整配置不能重复"):
        RetrievalRankingReport.model_validate(duplicate)


def test_mock_report_has_40_cases_category_breakdown_and_no_body() -> None:
    report = build_report()
    serialized = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)

    assert all(item.metrics.case_count == 40 for item in report.candidates)
    assert all(item.metrics.scored_case_count == 28 for item in report.candidates)
    assert all(len(item.category_metrics) == 5 for item in report.candidates)
    assert '"question"' not in serialized
    assert '"answer_text"' not in serialized
    assert '"content"' not in serialized
    assert '"page_content"' not in serialized
    assert '"prompt"' not in serialized.casefold()
    assert "不会进入报告的正文" not in serialized
    assert "固定Mock片段" not in serialized


def test_checked_in_mock_report_and_schema_are_reproducible() -> None:
    report = build_report()
    checked = json.loads(
        (EVALUATION_ROOT / "reports" / "retrieval_ranking_mock_v1.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (
            EVALUATION_ROOT
            / "schemas"
            / "retrieval_ranking_report_v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert checked == report.model_dump(mode="json")
    assert RetrievalRankingReport.model_validate(checked) == report
    assert schema == RetrievalRankingReport.model_json_schema()
