"""使用同一eval_v1生成可归因的候选方案Mock对比报告。"""

import hashlib
from datetime import datetime, timezone

from app.evaluation.comparison_schemas import (
    CandidateAnswerConfiguration,
    CandidateComparisonResult,
    CandidateProfile,
    CandidateRerankConfiguration,
    CandidateRetrievalConfiguration,
    CandidateStageMetrics,
    CandidateTechnicalConfiguration,
    RagComparisonReport,
    calculate_configuration_fingerprint,
)
from app.evaluation.fake_adapters import (
    FixedFakeAnswerAdapter,
    FixedFakeRetrievalAdapter,
)
from app.evaluation.runner import calculate_evaluation_checksum, run_evaluation
from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.core.config import Settings
from app.modules.rag.adapters import RAG_SYSTEM_PROMPT
from app.schemas.chat import ChatRequest


def _profile(
    *,
    candidate_id: str,
    display_name: str,
    hybrid_enabled: bool,
    rerank_enabled: bool,
) -> CandidateProfile:
    defaults = Settings.model_fields
    configuration = CandidateTechnicalConfiguration(
        profile_version="rag_candidate_profile_v1",
        retrieval=CandidateRetrievalConfiguration(
            query_builder_version="current_history_query_v1",
            vector_adapter="current_chroma_read_only_v1",
            embedding_model=str(defaults["embedding_model_name"].default),
            chroma_collection=str(defaults["chroma_collection_name"].default),
            top_k=int(ChatRequest.model_fields["top_k"].default),
            minimum_relevance_score=defaults["rag_min_relevance_score"].default,
            metadata_filters={},
            hybrid_enabled=hybrid_enabled,
            keyword_adapter="chroma_bm25_style_v1",
            vector_weight=float(defaults["rag_hybrid_vector_weight"].default),
            keyword_weight=float(defaults["rag_hybrid_keyword_weight"].default),
            rrf_k=int(defaults["rag_hybrid_rrf_k"].default),
        ),
        rerank=CandidateRerankConfiguration(
            enabled=rerank_enabled,
            adapter="dashscope_text_rerank_v1",
            model=str(defaults["rag_rerank_model_name"].default),
            max_candidates=int(defaults["rag_rerank_max_candidates"].default),
            timeout_seconds=float(defaults["rag_rerank_timeout_seconds"].default),
            max_input_tokens=int(defaults["rag_rerank_max_input_tokens"].default),
            input_price_per_million_tokens_cny=float(
                defaults[
                    "rag_rerank_input_price_per_million_tokens_cny"
                ].default
            ),
            max_estimated_cost_cny=float(
                defaults["rag_rerank_max_estimated_cost_cny"].default
            ),
        ),
        answer=CandidateAnswerConfiguration(
            adapter="current_qwen_read_only_v1",
            model=str(defaults["chat_model_name"].default),
            prompt_sha256=hashlib.sha256(
                RAG_SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
            max_output_tokens=2048,
        ),
    )
    return CandidateProfile(
        candidate_id=candidate_id,
        display_name=display_name,
        configuration=configuration,
        configuration_fingerprint=calculate_configuration_fingerprint(
            configuration
        ),
    )


def build_candidate_profiles() -> list[CandidateProfile]:
    return [
        _profile(
            candidate_id="vector_baseline_v1",
            display_name="冻结向量检索基线",
            hybrid_enabled=False,
            rerank_enabled=False,
        ),
        _profile(
            candidate_id="hybrid_rrf_v1",
            display_name="向量与关键词加权RRF",
            hybrid_enabled=True,
            rerank_enabled=False,
        ),
        _profile(
            candidate_id="hybrid_rrf_rerank_v1",
            display_name="加权RRF与可选重排",
            hybrid_enabled=True,
            rerank_enabled=True,
        ),
    ]


def _run_mock_candidate(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    profile: CandidateProfile,
    retrieval_pipeline_latency_ms: float,
    rerank_latency_ms: float | None,
    generated_at: datetime,
) -> CandidateComparisonResult:
    retrieval = FixedFakeRetrievalAdapter(
        evaluation_set,
        latency_ms=retrieval_pipeline_latency_ms,
    )
    retrieval.adapter_name = f"mock_{profile.candidate_id}_retrieval"
    answer = FixedFakeAnswerAdapter(evaluation_set, latency_ms=8.0)
    answer.adapter_name = "mock_shared_answer_v1"
    report = run_evaluation(
        evaluation_set=evaluation_set,
        corpus=corpus,
        category_config=category_config,
        retrieval_port=retrieval,
        answer_port=answer,
        report_version=f"{profile.candidate_id}_mock_v1",
        run_kind="candidate_comparison",
        generated_at=generated_at,
    )
    case_count = report.metrics.completed_case_count
    rerank_enabled = profile.configuration.rerank.enabled
    rerank_tokens = case_count * 200 if rerank_enabled else 0
    rerank_cost = round(
        rerank_tokens
        * profile.configuration.rerank.input_price_per_million_tokens_cny
        / 1_000_000,
        6,
    )
    return CandidateComparisonResult(
        profile=profile,
        evaluation_report=report,
        stage_metrics=CandidateStageMetrics(
            retrieval_pipeline_observed_case_count=(
                report.metrics.retrieval_observed_case_count
            ),
            mean_retrieval_pipeline_latency_ms=(
                report.metrics.mean_retrieval_latency_ms
            ),
            rerank_attempted_case_count=case_count if rerank_enabled else 0,
            rerank_external_call_count=case_count if rerank_enabled else 0,
            rerank_succeeded_case_count=case_count if rerank_enabled else 0,
            rerank_fallback_case_count=0,
            rerank_observed_case_count=case_count if rerank_enabled else 0,
            mean_rerank_latency_ms=rerank_latency_ms,
            rerank_usage_reported_case_count=case_count if rerank_enabled else 0,
            rerank_usage_missing_case_count=0,
            rerank_input_tokens=rerank_tokens,
            rerank_estimated_cost_cny=rerank_cost,
            rerank_estimated_cost_complete=True,
            embedding_tokens_reserved=0,
            embedding_estimated_cost_cny=0.0,
            answer_observed_case_count=report.metrics.answer_observed_case_count,
            mean_answer_latency_ms=report.metrics.mean_answer_latency_ms,
            mean_total_pipeline_latency_ms=round(
                retrieval_pipeline_latency_ms + 8.0, 6
            ),
            total_tokens=report.metrics.total_tokens + rerank_tokens,
            total_estimated_cost_cny=round(
                report.metrics.estimated_cost_cny + rerank_cost, 6
            ),
            total_estimated_cost_complete=(
                report.metrics.estimated_cost_complete
            ),
        ),
    )


def build_mock_comparison(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
) -> RagComparisonReport:
    generated_at = datetime(2026, 7, 19, tzinfo=timezone.utc)
    profiles = build_candidate_profiles()
    candidates = [
        _run_mock_candidate(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=category_config,
            profile=profiles[0],
            retrieval_pipeline_latency_ms=4.0,
            rerank_latency_ms=None,
            generated_at=generated_at,
        ),
        _run_mock_candidate(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=category_config,
            profile=profiles[1],
            retrieval_pipeline_latency_ms=6.0,
            rerank_latency_ms=None,
            generated_at=generated_at,
        ),
        _run_mock_candidate(
            evaluation_set=evaluation_set,
            corpus=corpus,
            category_config=category_config,
            profile=profiles[2],
            retrieval_pipeline_latency_ms=7.0,
            rerank_latency_ms=1.0,
            generated_at=generated_at,
        ),
    ]
    return RagComparisonReport(
        schema_version="rag_comparison_report_v1",
        report_version="rag_v1_2_mock_comparison_v1",
        run_kind="mock_comparison",
        generated_at=generated_at,
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=evaluation_set.corpus_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        candidates=candidates,
    )
