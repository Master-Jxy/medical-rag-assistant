"""任务7.6两个新候选使用的只读真实评估适配器。"""

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from langchain_core.documents import Document

from app.evaluation.budget import EvaluationBudget
from app.evaluation.comparison_schemas import CandidateProfile
from app.evaluation.current_adapters import RetrievedContextStore
from app.evaluation.ports import (
    EvaluationQuery,
    RetrievalObservation,
    TokenUsageObservation,
)
from app.infrastructure.reranker import DashScopeRerankAdapter
from app.modules.rag.adapters import (
    CurrentChromaKnowledgeSearchAdapter,
    CurrentQueryBuilderAdapter,
)
from app.modules.rag.hybrid_search import HybridKnowledgeSearchAdapter
from app.modules.rag.keyword_search import ChromaKeywordSearchAdapter
from app.modules.rag.policies import HybridSearchPolicy, RerankPolicy
from app.modules.rag.ports import RerankPort, RetrievedChunk


@dataclass(frozen=True)
class CandidateRerankObservation:
    attempted: bool
    external_call: bool
    succeeded: bool
    fallback_used: bool
    latency_ms: float | None
    usage: TokenUsageObservation | None


class CandidateRetrievalAdapter:
    """只读执行混合召回与可选重排，并把正文仅保存在进程内。"""

    def __init__(
        self,
        *,
        profile: CandidateProfile,
        vector_store,
        context_store: RetrievedContextStore,
        budget: EvaluationBudget,
        reranker: RerankPort | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self.adapter_name = f"{profile.candidate_id}_read_only_v1"
        self.profile = profile
        self._context_store = context_store
        self._budget = budget
        self._reranker = reranker
        self._clock = clock
        self.rerank_observations: dict[str, CandidateRerankObservation] = {}
        vector_search = CurrentChromaKnowledgeSearchAdapter(vector_store)
        config = profile.configuration.retrieval
        if config.hybrid_enabled:
            self._search = HybridKnowledgeSearchAdapter(
                vector_search,
                ChromaKeywordSearchAdapter(vector_store),
                HybridSearchPolicy(
                    enabled=True,
                    vector_weight=config.vector_weight,
                    keyword_weight=config.keyword_weight,
                    rrf_k=config.rrf_k,
                ),
            )
        else:
            self._search = vector_search
        self._query_builder = CurrentQueryBuilderAdapter()
        rerank_config = profile.configuration.rerank
        self._rerank_policy = RerankPolicy(
            enabled=rerank_config.enabled,
            model_name=rerank_config.model,
            max_candidates=rerank_config.max_candidates,
            timeout_seconds=rerank_config.timeout_seconds,
            max_input_tokens=rerank_config.max_input_tokens,
            input_price_per_million_tokens_cny=(
                rerank_config.input_price_per_million_tokens_cny
            ),
            max_estimated_cost_cny=rerank_config.max_estimated_cost_cny,
        )
        if self._rerank_policy.enabled and self._reranker is None:
            raise ValueError("启用重排候选时必须提供只读RerankPort")

    def retrieve(self, query: EvaluationQuery) -> RetrievalObservation:
        started = self._clock()
        retrieval_query = self._query_builder.build(
            query.question, list(query.history)
        )
        chunks = self._search.search(
            retrieval_query,
            self.profile.configuration.retrieval.top_k,
        )
        chunks = self._apply_rerank(query.case_id, retrieval_query, chunks)
        self._context_store.put(
            query.case_id,
            [self._to_document(chunk) for chunk in chunks],
        )
        source_ids = tuple(self._require_document_id(chunk) for chunk in chunks)
        return RetrievalObservation(
            source_document_ids=source_ids,
            latency_ms=(self._clock() - started) * 1000,
        )

    def _apply_rerank(
        self,
        case_id: str,
        retrieval_query: str,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        if not self._rerank_policy.enabled or not chunks:
            self.rerank_observations[case_id] = CandidateRerankObservation(
                attempted=False,
                external_call=False,
                succeeded=False,
                fallback_used=False,
                latency_ms=None,
                usage=None,
            )
            return chunks
        candidates = chunks[: self._rerank_policy.max_candidates]
        reserved_tokens = self._rerank_policy.estimate_input_tokens(
            retrieval_query, candidates
        )
        reserved_cost = self._rerank_policy.estimate_cost_cny(reserved_tokens)
        if (
            reserved_tokens > self._rerank_policy.max_input_tokens
            or reserved_cost > self._rerank_policy.max_estimated_cost_cny
        ):
            self.rerank_observations[case_id] = CandidateRerankObservation(
                attempted=True,
                external_call=False,
                succeeded=False,
                fallback_used=True,
                latency_ms=0.0,
                usage=None,
            )
            return chunks

        self._budget.before_rerank()
        started = self._clock()
        try:
            result = self._reranker.rerank(  # type: ignore[union-attr]
                retrieval_query,
                candidates,
                min(self.profile.configuration.retrieval.top_k, len(candidates)),
            )
        except Exception:
            self._budget.record_rerank_failure()
            elapsed_ms = (self._clock() - started) * 1000
            self.rerank_observations[case_id] = CandidateRerankObservation(
                attempted=True,
                external_call=True,
                succeeded=False,
                fallback_used=True,
                latency_ms=elapsed_ms,
                usage=None,
            )
            return chunks
        usage = TokenUsageObservation(
            input_tokens=result.usage.input_tokens,
            output_tokens=0,
            estimated_cost_cny=result.usage.estimated_cost_cny,
        )
        self._budget.record_rerank_usage(usage)
        elapsed_ms = (self._clock() - started) * 1000
        top_n = min(
            self.profile.configuration.retrieval.top_k, len(candidates)
        )
        candidate_ids = {id(candidate) for candidate in candidates}
        valid_result = (
            result.usage.request_count == 1
            and len(result.chunks) == top_n
            and all(id(chunk) in candidate_ids for chunk in result.chunks)
        )
        if not valid_result:
            self.rerank_observations[case_id] = CandidateRerankObservation(
                attempted=True,
                external_call=True,
                succeeded=False,
                fallback_used=True,
                latency_ms=elapsed_ms,
                usage=usage,
            )
            return chunks
        self.rerank_observations[case_id] = CandidateRerankObservation(
            attempted=True,
            external_call=True,
            succeeded=True,
            fallback_used=False,
            latency_ms=elapsed_ms,
            usage=usage,
        )
        return result.chunks

    @staticmethod
    def _require_document_id(chunk: RetrievedChunk) -> str:
        document_id = str(chunk.document_id or "").strip()
        if not document_id:
            raise ValueError("候选检索片段缺少document_id")
        return document_id

    @staticmethod
    def _to_document(chunk: RetrievedChunk) -> Document:
        metadata = dict(chunk.metadata)
        metadata["document_id"] = CandidateRetrievalAdapter._require_document_id(
            chunk
        )
        metadata["file_name"] = chunk.file_name
        if chunk.page is not None:
            metadata["page"] = chunk.page - 1
        return Document(page_content=chunk.content, metadata=metadata)


def create_candidate_reranker(
    profile: CandidateProfile,
    *,
    api_key: str,
    call=None,
) -> RerankPort | None:
    config = profile.configuration.rerank
    if not config.enabled:
        return None
    return DashScopeRerankAdapter(
        api_key=api_key,
        model_name=config.model,
        timeout_seconds=config.timeout_seconds,
        input_price_per_million_tokens_cny=(
            config.input_price_per_million_tokens_cny
        ),
        call=call,
    )
