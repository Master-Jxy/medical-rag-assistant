"""Read-only adapters that share one retrieval input across four ranking profiles."""

from dataclasses import dataclass

from app.evaluation.budget import EvaluationBudget
from app.evaluation.ports import EvaluationQuery, TokenUsageObservation
from app.evaluation.retrieval_ranking_real_schemas import RankingCaseExecution
from app.modules.rag.adapters import CurrentQueryBuilderAdapter
from app.modules.rag.candidate_selection import CandidateSelectionPolicy, CandidateSelectionResult
from app.modules.rag.hybrid_search import fuse_ranked_chunks
from app.modules.rag.policies import HybridSearchPolicy
from app.modules.rag.ports import KnowledgeSearchPort, RerankPort, RetrievedChunk


@dataclass(frozen=True)
class SharedRankingCaseResult:
    case_id: str
    candidates: dict[str, CandidateSelectionResult]
    execution: RankingCaseExecution


class SharedRetrievalRankingAdapter:
    """One vector call and one local keyword scan per case; no answer generation."""

    def __init__(
        self,
        *,
        vector_search: KnowledgeSearchPort,
        keyword_search: KnowledgeSearchPort,
        reranker: RerankPort,
        budget: EvaluationBudget,
        hybrid_policy: HybridSearchPolicy,
        query_builder: CurrentQueryBuilderAdapter | None = None,
        selection_policy: CandidateSelectionPolicy | None = None,
    ) -> None:
        self._vector_search = vector_search
        self._keyword_search = keyword_search
        self._reranker = reranker
        self._budget = budget
        self._hybrid_policy = hybrid_policy
        self._query_builder = query_builder or CurrentQueryBuilderAdapter()
        self._selection = selection_policy or CandidateSelectionPolicy()
        self.keyword_scans = 0

    def evaluate(self, query: EvaluationQuery) -> SharedRankingCaseResult:
        retrieval_query = self._query_builder.build(query.question, list(query.history))
        errors: list[str] = []
        self._budget.before_retrieval()
        try:
            vector = self._vector_search.search(retrieval_query, 12)
            vector_ok = True
        except Exception:
            vector = []
            vector_ok = False
            errors.append("vector")

        self.keyword_scans += 1
        try:
            keyword = self._keyword_search.search(retrieval_query, 12)
            keyword_ok = True
        except Exception:
            keyword = []
            keyword_ok = False
            errors.append("keyword")

        hybrid = (
            fuse_ranked_chunks(vector, keyword, 12, self._hybrid_policy)
            if keyword_ok
            else list(vector)
        )
        reference = self._selection.select(vector, enforce_document_limit=False)
        vector_diverse = self._selection.select(vector, enforce_document_limit=True)
        hybrid_diverse = self._selection.select(hybrid, enforce_document_limit=True)

        rerank_attempted = bool(hybrid_diverse.ranked_candidates)
        rerank_ok = False
        rerank_fallback = False
        reranked = hybrid_diverse
        if rerank_attempted:
            self._budget.before_rerank()
            try:
                pool = list(hybrid_diverse.ranked_candidates)
                result = self._reranker.rerank(
                    retrieval_query, pool, min(4, len(pool))
                )
            except Exception:
                self._budget.record_rerank_failure()
                errors.append("rerank")
                rerank_fallback = True
            else:
                usage = TokenUsageObservation(
                    input_tokens=result.usage.input_tokens,
                    output_tokens=0,
                    estimated_cost_cny=result.usage.estimated_cost_cny,
                )
                self._budget.record_rerank_usage(usage)
                valid = (
                    result.usage.request_count == 1
                    and len(result.chunks) == min(4, len(pool))
                    and all(id(chunk) in {id(item) for item in pool} for chunk in result.chunks)
                )
                if valid:
                    rerank_ok = True
                    reranked = CandidateSelectionResult(
                        ranked_candidates=hybrid_diverse.ranked_candidates,
                        final_chunks=tuple(result.chunks),
                    )
                else:
                    errors.append("rerank")
                    rerank_fallback = True

        return SharedRankingCaseResult(
            case_id=query.case_id,
            candidates={
                "vector_top4_reference": reference,
                "vector_wide_diverse_v1": vector_diverse,
                "hybrid_wide_diverse_v1": hybrid_diverse,
                "hybrid_wide_diverse_rerank_v1": reranked,
            },
            execution=RankingCaseExecution(
                case_id=query.case_id,
                vector_succeeded=vector_ok,
                keyword_succeeded=keyword_ok,
                rerank_attempted=rerank_attempted,
                rerank_succeeded=rerank_ok,
                hybrid_fallback_used=not keyword_ok,
                rerank_fallback_used=rerank_fallback,
                error_stages=errors,
            ),
        )
