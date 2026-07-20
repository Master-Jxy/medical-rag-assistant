"""候选池文档级排序指标、固定Profile与确定性Mock编排。"""

import math
from datetime import datetime, timezone
from statistics import fmean

from app.core.config import Settings
from app.evaluation.retrieval_ranking_schemas import (
    RetrievalRankingAggregateMetrics,
    RetrievalRankingCandidateResult,
    RetrievalRankingCaseMetrics,
    RetrievalRankingCaseResult,
    RetrievalRankingCategoryMetrics,
    RetrievalRankingConfiguration,
    RetrievalRankingProfile,
    RetrievalRankingReport,
    calculate_ranking_configuration_fingerprint,
)
from app.evaluation.runner import calculate_evaluation_checksum
from app.evaluation.schemas import CorpusManifest, EvaluationCase, EvaluationCategory, EvaluationSet
from app.evaluation.validation import validate_evaluation_set
from app.modules.rag.candidate_selection import CandidateSelectionPolicy
from app.modules.rag.ports import RetrievedChunk


def _profile(
    *,
    candidate_id: str,
    display_name: str,
    retrieval_mode: str,
    diversity_enabled: bool,
    rerank_enabled: bool,
) -> RetrievalRankingProfile:
    defaults = Settings.model_fields
    configuration = RetrievalRankingConfiguration(
        profile_version="retrieval_ranking_profile_v1",
        candidate_pool_size=12,
        max_chunks_per_document=2,
        final_top_k=4,
        vector_adapter="current_chroma_read_only_v1",
        keyword_adapter="chroma_bm25_style_v1",
        retrieval_mode=retrieval_mode,
        vector_weight=float(defaults["rag_hybrid_vector_weight"].default),
        keyword_weight=float(defaults["rag_hybrid_keyword_weight"].default),
        rrf_k=int(defaults["rag_hybrid_rrf_k"].default),
        document_diversity_enabled=diversity_enabled,
        rerank_enabled=rerank_enabled,
        rerank_adapter="dashscope_text_rerank_v1",
        rerank_model=str(defaults["rag_rerank_model_name"].default),
        shared_vector_and_keyword_inputs=True,
    )
    return RetrievalRankingProfile(
        candidate_id=candidate_id,
        display_name=display_name,
        configuration=configuration,
        configuration_fingerprint=calculate_ranking_configuration_fingerprint(
            configuration
        ),
    )


def build_retrieval_ranking_profiles() -> list[RetrievalRankingProfile]:
    return [
        _profile(
            candidate_id="vector_top4_reference",
            display_name="同一次向量前12直接截取前4",
            retrieval_mode="vector",
            diversity_enabled=False,
            rerank_enabled=False,
        ),
        _profile(
            candidate_id="vector_wide_diverse_v1",
            display_name="向量宽召回与文档配额",
            retrieval_mode="vector",
            diversity_enabled=True,
            rerank_enabled=False,
        ),
        _profile(
            candidate_id="hybrid_wide_diverse_v1",
            display_name="宽候选混合RRF与文档配额",
            retrieval_mode="hybrid_rrf",
            diversity_enabled=True,
            rerank_enabled=False,
        ),
        _profile(
            candidate_id="hybrid_wide_diverse_rerank_v1",
            display_name="宽候选混合RRF、文档配额与重排",
            retrieval_mode="hybrid_rrf",
            diversity_enabled=True,
            rerank_enabled=True,
        ),
    ]


def _document_ranking(chunks: tuple[RetrievedChunk, ...]) -> list[str]:
    ranking: list[str] = []
    seen: set[str] = set()
    for index, chunk in enumerate(chunks):
        document_id = (chunk.document_id or "").strip()
        identity = document_id if document_id else f"unknown:{index + 1}"
        if identity not in seen:
            seen.add(identity)
            ranking.append(identity)
    return ranking


def calculate_retrieval_ranking_metrics(
    *,
    expected_source_document_ids: list[str],
    ranked_candidates: tuple[RetrievedChunk, ...],
    final_chunks: tuple[RetrievedChunk, ...],
) -> tuple[RetrievalRankingCaseMetrics, list[str], list[str]]:
    ranked_at_10 = _document_ranking(ranked_candidates[:10])
    final_document_ids = [
        (chunk.document_id or "").strip() or f"unknown:{index + 1}"
        for index, chunk in enumerate(final_chunks)
    ]
    final_ranking = []
    for document_id in final_document_ids:
        if document_id not in final_ranking:
            final_ranking.append(document_id)
    if not expected_source_document_ids:
        return RetrievalRankingCaseMetrics(), ranked_at_10, final_document_ids

    expected = set(expected_source_document_ids)
    top_4 = final_ranking[:4]
    top_10 = ranked_at_10[:10]
    recall_4 = len(expected.intersection(top_4)) / len(expected)
    recall_10 = len(expected.intersection(top_10)) / len(expected)
    first_relevant = next(
        (index for index, document_id in enumerate(top_4, start=1) if document_id in expected),
        None,
    )
    mrr = 0.0 if first_relevant is None else 1 / first_relevant
    dcg = sum(
        1 / math.log2(index + 1)
        for index, document_id in enumerate(top_4, start=1)
        if document_id in expected
    )
    ideal_count = min(len(expected), 4)
    ideal_dcg = sum(1 / math.log2(index + 1) for index in range(1, ideal_count + 1))
    unique_count = len(set(final_document_ids))
    duplicate_ratio = (
        0.0
        if not final_document_ids
        else 1 - unique_count / len(final_document_ids)
    )
    return (
        RetrievalRankingCaseMetrics(
            source_recall_at_4=round(recall_4, 6),
            source_recall_at_10=round(recall_10, 6),
            full_source_hit_at_4=expected.issubset(top_4),
            full_source_hit_at_10=expected.issubset(top_10),
            mrr_at_4=round(mrr, 6),
            ndcg_at_4=round(dcg / ideal_dcg, 6),
            unique_document_count_at_4=unique_count,
            duplicate_chunk_ratio_at_4=round(duplicate_ratio, 6),
        ),
        ranked_at_10,
        final_document_ids,
    )


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 6) if values else None


def aggregate_retrieval_ranking_cases(
    cases: list[RetrievalRankingCaseResult],
) -> RetrievalRankingAggregateMetrics:
    scored = [item.metrics for item in cases if item.metrics.source_recall_at_4 is not None]
    return RetrievalRankingAggregateMetrics(
        case_count=len(cases),
        scored_case_count=len(scored),
        mean_source_recall_at_4=_mean([item.source_recall_at_4 for item in scored]),
        mean_source_recall_at_10=_mean([item.source_recall_at_10 for item in scored]),
        full_source_hit_rate_at_4=_mean([float(item.full_source_hit_at_4) for item in scored]),
        full_source_hit_rate_at_10=_mean([float(item.full_source_hit_at_10) for item in scored]),
        mean_mrr_at_4=_mean([item.mrr_at_4 for item in scored]),
        mean_ndcg_at_4=_mean([item.ndcg_at_4 for item in scored]),
        mean_unique_document_count_at_4=_mean(
            [float(item.unique_document_count_at_4) for item in scored]
        ),
        mean_duplicate_chunk_ratio_at_4=_mean(
            [item.duplicate_chunk_ratio_at_4 for item in scored]
        ),
    )


def _mock_chunks(
    case: EvaluationCase,
    corpus_document_ids: list[str],
    *,
    hybrid: bool,
    reranked: bool,
) -> list[RetrievedChunk]:
    expected = list(case.expected_source_document_ids)
    distractors = [item for item in corpus_document_ids if item not in expected]
    primary = expected[0] if expected else distractors[0]
    sequence = [primary, primary]
    if hybrid:
        sequence.extend(expected[1:])
        sequence.extend(distractors[: 12 - len(sequence)])
    else:
        sequence.extend(distractors[:1])
        sequence.extend(expected[1:])
        sequence.extend([primary])
        sequence.extend(distractors[1 : 12 - len(sequence) + 1])
    sequence = sequence[:12]
    if reranked:
        sequence = expected + [item for item in sequence if item not in expected]
        sequence = sequence[:12]
    return [
        RetrievedChunk(
            content=f"固定Mock片段{index}",
            file_name=f"mock-{index}.txt",
            page=index,
            chunk_id=f"{case.case_id}:mock:{index}",
            document_id=document_id,
        )
        for index, document_id in enumerate(sequence, start=1)
    ]


def _run_mock_candidate(
    profile: RetrievalRankingProfile,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
) -> RetrievalRankingCandidateResult:
    policy = CandidateSelectionPolicy()
    corpus_document_ids = [item.document_id for item in corpus.documents]
    cases: list[RetrievalRankingCaseResult] = []
    config = profile.configuration
    for case in evaluation_set.cases:
        chunks = _mock_chunks(
            case,
            corpus_document_ids,
            hybrid=config.retrieval_mode == "hybrid_rrf",
            reranked=config.rerank_enabled,
        )
        selection = policy.select(
            chunks,
            enforce_document_limit=config.document_diversity_enabled,
        )
        metrics, ranked_ids, final_ids = calculate_retrieval_ranking_metrics(
            expected_source_document_ids=case.expected_source_document_ids,
            ranked_candidates=selection.ranked_candidates,
            final_chunks=selection.final_chunks,
        )
        cases.append(
            RetrievalRankingCaseResult(
                case_id=case.case_id,
                category=case.category,
                expected_source_document_ids=case.expected_source_document_ids,
                ranked_document_ids_at_10=ranked_ids,
                final_chunk_document_ids=final_ids,
                metrics=metrics,
            )
        )
    category_metrics = []
    for category in EvaluationCategory:
        category_cases = [item for item in cases if item.category == category]
        category_metrics.append(
            RetrievalRankingCategoryMetrics(
                category=category,
                **aggregate_retrieval_ranking_cases(category_cases).model_dump(),
            )
        )
    return RetrievalRankingCandidateResult(
        profile=profile,
        metrics=aggregate_retrieval_ranking_cases(cases),
        category_metrics=category_metrics,
        cases=cases,
    )


def build_mock_retrieval_ranking_report(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
) -> RetrievalRankingReport:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    return RetrievalRankingReport(
        schema_version="retrieval_ranking_report_v1",
        report_version="retrieval_ranking_mock_v1",
        run_kind="mock_retrieval_ranking",
        generated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=evaluation_set.corpus_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        candidates=[
            _run_mock_candidate(profile, evaluation_set, corpus)
            for profile in build_retrieval_ranking_profiles()
        ],
    )
