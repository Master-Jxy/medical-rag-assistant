"""关键词与向量检索的可关闭融合适配器。"""

import hashlib
import logging
from dataclasses import replace

from app.core.config import Settings
from app.infrastructure.vector_store import VectorStoreService
from app.modules.rag.adapters import CurrentChromaKnowledgeSearchAdapter
from app.modules.rag.keyword_search import ChromaKeywordSearchAdapter
from app.modules.rag.policies import HybridSearchPolicy
from app.modules.rag.ports import (
    KeywordSearchPort,
    KnowledgeSearchOptions,
    KnowledgeSearchPort,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)


def fuse_ranked_chunks(
    vector_results: list[RetrievedChunk],
    keyword_results: list[RetrievedChunk],
    top_k: int,
    policy: HybridSearchPolicy,
) -> list[RetrievedChunk]:
    """Fuse already-fetched rankings without performing another external search."""
    chunks: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    modes: dict[str, set[str]] = {}
    for mode, weight, results in (
        ("vector", policy.vector_weight, vector_results),
        ("keyword", policy.keyword_weight, keyword_results),
    ):
        for rank, chunk in enumerate(results, start=1):
            identity = HybridKnowledgeSearchAdapter._identity(chunk)
            chunks.setdefault(identity, chunk)
            scores[identity] = scores.get(identity, 0.0) + weight / (
                policy.rrf_k + rank
            )
            modes.setdefault(identity, set()).add(mode)
    ranked = sorted(scores, key=lambda key: (-scores[key], key))[:top_k]
    return [
        replace(
            chunks[key],
            relevance_score=scores[key],
            metadata={
                **chunks[key].metadata,
                "retrieval_modes": ",".join(sorted(modes[key])),
            },
        )
        for key in ranked
    ]


class HybridKnowledgeSearchAdapter:
    """以加权RRF融合两路排名；关键词故障时回退向量结果。"""

    def __init__(
        self,
        vector_search: KnowledgeSearchPort,
        keyword_search: KeywordSearchPort,
        policy: HybridSearchPolicy,
    ) -> None:
        if not policy.enabled:
            raise ValueError("混合检索适配器只能在开关启用时创建")
        self.vector_search = vector_search
        self.keyword_search = keyword_search
        self.policy = policy

    def search(
        self,
        query: str,
        top_k: int,
        options: KnowledgeSearchOptions | None = None,
    ) -> list[RetrievedChunk]:
        vector_results = self.vector_search.search(query, top_k, options)
        try:
            keyword_results = self.keyword_search.search(query, top_k, options)
        except Exception as exc:
            logger.warning(
                "关键词检索失败，已回退向量结果",
                extra={"error_type": type(exc).__name__},
            )
            return vector_results
        return fuse_ranked_chunks(
            vector_results, keyword_results, top_k, self.policy
        )

    def _fuse(
        self,
        vector_results: list[RetrievedChunk],
        keyword_results: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        return fuse_ranked_chunks(
            vector_results, keyword_results, top_k, self.policy
        )

    @staticmethod
    def _identity(chunk: RetrievedChunk) -> str:
        content_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        owner = chunk.document_id or f"{chunk.file_name}:{chunk.page}"
        return f"{owner}:{content_hash}"


def create_current_knowledge_search(settings: Settings) -> KnowledgeSearchPort:
    """按开关组装当前向量检索或混合检索，不改变上层入口。"""
    vector_store = VectorStoreService(settings)
    vector_search = CurrentChromaKnowledgeSearchAdapter(vector_store)
    policy = HybridSearchPolicy.from_settings(settings)
    if not policy.enabled:
        return vector_search
    return HybridKnowledgeSearchAdapter(
        vector_search,
        ChromaKeywordSearchAdapter(vector_store),
        policy,
    )
