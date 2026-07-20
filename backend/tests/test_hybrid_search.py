from unittest.mock import Mock

import pytest
from langchain_core.documents import Document

from app.core.config import Settings
from app.modules.rag.adapters import CurrentChromaKnowledgeSearchAdapter
from app.modules.rag.hybrid_search import (
    HybridKnowledgeSearchAdapter,
    create_current_knowledge_search,
)
from app.modules.rag.keyword_search import (
    ChromaKeywordSearchAdapter,
    tokenize_for_keyword_search,
)
from app.modules.rag.policies import HybridSearchPolicy
from app.modules.rag.ports import (
    KnowledgeSearchOptions,
    RetrievalMetadataFilter,
    RetrievedChunk,
)


class FixedSearch:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, query, top_k, options=None):
        self.calls.append((query, top_k, options))
        if self.error:
            raise self.error
        return self.results


def chunk(name: str, content: str, document_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        content=content,
        file_name=name,
        page=None,
        document_id=document_id,
    )


def test_keyword_tokenizer_supports_chinese_bigrams_and_ascii_words() -> None:
    tokens = tokenize_for_keyword_search("Cardiac 心血管管理")

    assert "cardiac" in tokens
    assert "心血" in tokens
    assert "血管" in tokens
    assert "管理" in tokens


def test_keyword_search_ranks_matching_chunks_without_embedding() -> None:
    vector_store = Mock()
    vector_store.list_documents.return_value = [
        (
            "chunk-heart",
            Document(
                page_content="心血管系统负责血液循环和氧气运输。",
                metadata={"document_id": "heart", "file_name": "心血管.txt"},
            ),
        ),
        (
            "chunk-other",
            Document(
                page_content="神经系统包含中枢神经和周围神经。",
                metadata={"document_id": "nerve", "file_name": "神经.txt"},
            ),
        ),
    ]
    adapter = ChromaKeywordSearchAdapter(vector_store)
    options = KnowledgeSearchOptions(
        metadata_filter=RetrievalMetadataFilter(document_type="txt")
    )

    results = adapter.search("心血管循环", 2, options)

    vector_store.list_documents.assert_called_once_with(
        {"document_type": {"$eq": "txt"}}
    )
    assert [item.chunk_id for item in results] == ["chunk-heart"]
    assert results[0].relevance_score is not None
    assert results[0].relevance_score > 0


def test_weighted_rrf_deduplicates_and_promotes_dual_hit() -> None:
    first = chunk("A.txt", "A正文", "doc-a")
    shared_vector = chunk("B.txt", "共同正文", "doc-b")
    shared_keyword = chunk("B-renamed.txt", "共同正文", "doc-b")
    keyword_only = chunk("C.txt", "C正文", "doc-c")
    vector = FixedSearch([first, shared_vector])
    keyword = FixedSearch([shared_keyword, keyword_only])
    adapter = HybridKnowledgeSearchAdapter(
        vector,
        keyword,
        HybridSearchPolicy(enabled=True, vector_weight=0.7, keyword_weight=0.3),
    )

    results = adapter.search("问题", 3)

    assert [item.document_id for item in results] == ["doc-b", "doc-a", "doc-c"]
    assert results[0].metadata["retrieval_modes"] == "keyword,vector"
    assert len(results) == 3


def test_keyword_failure_returns_original_vector_order(caplog) -> None:
    vector_results = [
        chunk("A.txt", "A正文", "doc-a"),
        chunk("B.txt", "B正文", "doc-b"),
    ]
    adapter = HybridKnowledgeSearchAdapter(
        FixedSearch(vector_results),
        FixedSearch(error=RuntimeError("sensitive query must not be logged")),
        HybridSearchPolicy(enabled=True),
    )

    results = adapter.search("用户隐私问题", 2)

    assert results == vector_results
    assert "用户隐私问题" not in caplog.text
    assert "sensitive query" not in caplog.text
    assert "关键词检索失败" in caplog.text


def test_vector_failure_is_not_hidden_and_keyword_is_not_called() -> None:
    keyword = FixedSearch([chunk("A.txt", "正文", "doc-a")])
    adapter = HybridKnowledgeSearchAdapter(
        FixedSearch(error=RuntimeError("vector unavailable")),
        keyword,
        HybridSearchPolicy(enabled=True),
    )

    with pytest.raises(RuntimeError, match="vector unavailable"):
        adapter.search("问题", 2)
    assert keyword.calls == []


def test_feature_switch_builds_vector_only_or_hybrid(monkeypatch) -> None:
    import app.modules.rag.hybrid_search as hybrid_search

    vector_store = Mock()
    monkeypatch.setattr(
        hybrid_search,
        "VectorStoreService",
        lambda settings: vector_store,
    )

    disabled = create_current_knowledge_search(Settings(_env_file=None))
    enabled = create_current_knowledge_search(
        Settings(_env_file=None, rag_hybrid_search_enabled=True)
    )

    assert isinstance(disabled, CurrentChromaKnowledgeSearchAdapter)
    assert isinstance(enabled, HybridKnowledgeSearchAdapter)
    assert enabled.vector_search.vector_store is vector_store
    assert enabled.keyword_search.vector_store is vector_store


def test_enabled_hybrid_rejects_zero_total_weight() -> None:
    with pytest.raises(ValueError, match="至少需要一个正权重"):
        HybridSearchPolicy(enabled=True, vector_weight=0, keyword_weight=0)
