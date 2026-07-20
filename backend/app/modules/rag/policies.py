"""RAG检索接受条件与知识不足拒答策略。"""

from dataclasses import dataclass, field

from app.core.config import Settings
from app.modules.rag.ports import (
    KnowledgeSearchOptions,
    RetrievalMetadataFilter,
    RetrievedChunk,
)

DEFAULT_INSUFFICIENT_KNOWLEDGE_MESSAGE = "知识库资料不足，无法根据现有资料回答。"


@dataclass(frozen=True, slots=True)
class RagRetrievalPolicy:
    """把可选检索条件和无合格上下文时的固定拒答集中管理。"""

    search_options: KnowledgeSearchOptions = field(default_factory=KnowledgeSearchOptions)
    insufficient_knowledge_message: str = DEFAULT_INSUFFICIENT_KNOWLEDGE_MESSAGE

    def __post_init__(self) -> None:
        message = self.insufficient_knowledge_message.strip()
        if not message or len(message) > 500:
            raise ValueError("知识不足拒答文案必须为1-500个非空字符")
        object.__setattr__(self, "insufficient_knowledge_message", message)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RagRetrievalPolicy":
        return cls(
            search_options=KnowledgeSearchOptions(
                metadata_filter=RetrievalMetadataFilter(
                    department=settings.rag_filter_department,
                    topic=settings.rag_filter_topic,
                    document_type=settings.rag_filter_document_type,
                    knowledge_base_version=settings.rag_filter_knowledge_base_version,
                ),
                minimum_relevance_score=settings.rag_min_relevance_score,
            ),
            insufficient_knowledge_message=settings.rag_insufficient_knowledge_message,
        )


@dataclass(frozen=True, slots=True)
class HybridSearchPolicy:
    """混合检索开关与可解释的加权RRF参数。"""

    enabled: bool = False
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if not 0 <= self.vector_weight <= 1:
            raise ValueError("向量检索权重必须位于0到1之间")
        if not 0 <= self.keyword_weight <= 1:
            raise ValueError("关键词检索权重必须位于0到1之间")
        if self.enabled and self.vector_weight + self.keyword_weight <= 0:
            raise ValueError("混合检索至少需要一个正权重")
        if not 1 <= self.rrf_k <= 1000:
            raise ValueError("RRF常数必须位于1到1000之间")

    @classmethod
    def from_settings(cls, settings: Settings) -> "HybridSearchPolicy":
        return cls(
            enabled=settings.rag_hybrid_search_enabled,
            vector_weight=settings.rag_hybrid_vector_weight,
            keyword_weight=settings.rag_hybrid_keyword_weight,
            rrf_k=settings.rag_hybrid_rrf_k,
        )


@dataclass(frozen=True, slots=True)
class RerankPolicy:
    """重排开关及单次请求的候选、Token、费用和超时硬边界。"""

    enabled: bool = False
    model_name: str = "gte-rerank-v2"
    max_candidates: int = 10
    timeout_seconds: float = 3.0
    max_input_tokens: int = 12000
    input_price_per_million_tokens_cny: float = 0.8
    max_estimated_cost_cny: float = 0.01

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("重排模型名称不能为空")
        if not 1 <= self.max_candidates <= 100:
            raise ValueError("重排候选数必须位于1到100之间")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("重排超时必须大于0且不超过30秒")
        if not 1 <= self.max_input_tokens <= 120000:
            raise ValueError("重排输入Token上限必须位于1到120000之间")
        if self.input_price_per_million_tokens_cny < 0:
            raise ValueError("重排Token单价不能为负数")
        if self.max_estimated_cost_cny < 0:
            raise ValueError("重排费用上限不能为负数")

    def estimate_input_tokens(
        self,
        query: str,
        candidates: list[RetrievedChunk],
    ) -> int:
        """以UTF-8字节数保守预留Token，并按厂商公式重复计算Query。"""
        query_reserve = len(query.encode("utf-8")) * len(candidates)
        document_reserve = sum(
            len(candidate.content.encode("utf-8")) for candidate in candidates
        )
        return query_reserve + document_reserve

    def estimate_cost_cny(self, input_tokens: int) -> float:
        return (
            input_tokens
            * self.input_price_per_million_tokens_cny
            / 1_000_000
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "RerankPolicy":
        return cls(
            enabled=settings.rag_rerank_enabled,
            model_name=settings.rag_rerank_model_name,
            max_candidates=settings.rag_rerank_max_candidates,
            timeout_seconds=settings.rag_rerank_timeout_seconds,
            max_input_tokens=settings.rag_rerank_max_input_tokens,
            input_price_per_million_tokens_cny=(
                settings.rag_rerank_input_price_per_million_tokens_cny
            ),
            max_estimated_cost_cny=settings.rag_rerank_max_estimated_cost_cny,
        )
