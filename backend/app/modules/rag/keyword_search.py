"""基于Chroma现有片段的只读本地关键词检索。"""

import math
import re
from collections import Counter
from pathlib import Path

from langchain_core.documents import Document

from app.infrastructure.vector_store import VectorStoreService
from app.modules.rag.adapters import CurrentChromaKnowledgeSearchAdapter
from app.modules.rag.ports import KnowledgeSearchOptions, RetrievedChunk

ASCII_TOKEN = re.compile(r"[a-z0-9]+")
CHINESE_BLOCK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize_for_keyword_search(text: str) -> tuple[str, ...]:
    """英文按词、中文按单字和二元组切分，避免引入额外分词依赖。"""
    normalized = text.lower()
    tokens = ASCII_TOKEN.findall(normalized)
    for block in CHINESE_BLOCK.findall(normalized):
        tokens.extend(block)
        if len(block) > 1:
            tokens.extend(block[index : index + 2] for index in range(len(block) - 1))
    return tuple(tokens)


class ChromaKeywordSearchAdapter:
    """读取Chroma正文并使用确定性的BM25式分数排序。"""

    def __init__(self, vector_store: VectorStoreService) -> None:
        self.vector_store = vector_store

    def search(
        self,
        query: str,
        top_k: int,
        options: KnowledgeSearchOptions | None = None,
    ) -> list[RetrievedChunk]:
        active_options = options or KnowledgeSearchOptions()
        metadata_filter = CurrentChromaKnowledgeSearchAdapter._to_chroma_filter(
            active_options
        )
        stored = self.vector_store.list_documents(metadata_filter)
        query_tokens = tuple(dict.fromkeys(tokenize_for_keyword_search(query)))
        if not stored or not query_tokens:
            return []

        tokenized = [tokenize_for_keyword_search(document.page_content) for _, document in stored]
        average_length = sum(len(tokens) for tokens in tokenized) / len(tokenized)
        document_frequency = {
            token: sum(token in set(tokens) for tokens in tokenized)
            for token in query_tokens
        }
        scored: list[tuple[float, str, Document]] = []
        for (chunk_id, document), tokens in zip(stored, tokenized, strict=True):
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for token in query_tokens:
                frequency = counts[token]
                if not frequency:
                    continue
                seen = document_frequency[token]
                inverse_frequency = math.log(
                    1 + (len(stored) - seen + 0.5) / (seen + 0.5)
                )
                denominator = frequency + 1.5 * (
                    0.25 + 0.75 * length / max(average_length, 1)
                )
                score += inverse_frequency * frequency * 2.5 / denominator
            if score > 0:
                scored.append((score, chunk_id, document))

        scored.sort(key=lambda item: (-item[0], item[1]))
        results: list[RetrievedChunk] = []
        for score, chunk_id, document in scored[:top_k]:
            metadata = document.metadata or {}
            raw_source = str(
                metadata.get("source") or metadata.get("file_name") or "未知来源"
            )
            raw_page = metadata.get("page")
            results.append(
                RetrievedChunk(
                    content=document.page_content,
                    file_name=Path(raw_source).name,
                    page=raw_page + 1 if isinstance(raw_page, int) else None,
                    chunk_id=chunk_id,
                    document_id=(
                        str(metadata["document_id"])
                        if metadata.get("document_id") is not None
                        else None
                    ),
                    relevance_score=score,
                    metadata=dict(metadata),
                )
            )
        return results
