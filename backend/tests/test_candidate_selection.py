import pytest

from app.modules.rag.candidate_selection import CandidateSelectionPolicy
from app.modules.rag.ports import RetrievedChunk


def chunk(index: int, document_id: str | None) -> RetrievedChunk:
    return RetrievedChunk(
        content=f"片段{index}",
        file_name=f"资料{index}.txt",
        page=index,
        chunk_id=f"chunk-{index}",
        document_id=document_id,
    )


def test_policy_applies_stable_pool_document_quota_and_final_limit() -> None:
    chunks = [
        chunk(1, "doc-a"),
        chunk(2, "doc-a"),
        chunk(3, "doc-a"),
        chunk(4, "doc-b"),
        chunk(5, "doc-c"),
        chunk(6, "doc-d"),
    ]
    policy = CandidateSelectionPolicy(
        candidate_pool_size=5,
        max_chunks_per_document=2,
        final_top_k=3,
    )

    result = policy.select(chunks, enforce_document_limit=True)

    assert [item.chunk_id for item in result.ranked_candidates] == [
        "chunk-1",
        "chunk-2",
        "chunk-4",
        "chunk-5",
    ]
    assert [item.chunk_id for item in result.final_chunks] == [
        "chunk-1",
        "chunk-2",
        "chunk-4",
    ]


def test_reference_mode_keeps_original_top_order_without_document_limit() -> None:
    chunks = [chunk(index, "doc-a") for index in range(1, 6)]
    policy = CandidateSelectionPolicy(
        candidate_pool_size=4,
        max_chunks_per_document=2,
        final_top_k=3,
    )

    result = policy.select(chunks, enforce_document_limit=False)

    assert [item.chunk_id for item in result.ranked_candidates] == [
        "chunk-1",
        "chunk-2",
        "chunk-3",
        "chunk-4",
    ]
    assert [item.chunk_id for item in result.final_chunks] == [
        "chunk-1",
        "chunk-2",
        "chunk-3",
    ]


def test_missing_document_ids_are_never_merged_into_one_quota_bucket() -> None:
    chunks = [chunk(index, None) for index in range(1, 5)]
    policy = CandidateSelectionPolicy(
        candidate_pool_size=4,
        max_chunks_per_document=1,
        final_top_k=4,
    )

    result = policy.select(chunks, enforce_document_limit=True)

    assert result.ranked_candidates == tuple(chunks)
    assert result.final_chunks == tuple(chunks)


@pytest.mark.parametrize(
    "values",
    [
        {"candidate_pool_size": 0},
        {"max_chunks_per_document": 0},
        {"final_top_k": 0},
        {"candidate_pool_size": 3, "final_top_k": 4},
    ],
)
def test_policy_rejects_invalid_bounds(values) -> None:
    with pytest.raises(ValueError):
        CandidateSelectionPolicy(**values)
