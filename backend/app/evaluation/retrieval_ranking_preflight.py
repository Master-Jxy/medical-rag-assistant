"""No-cost preflight for the shared-input real retrieval-ranking run."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.evaluation.preflight import read_chroma_collection_count
from app.evaluation.retrieval_ranking import build_retrieval_ranking_profiles
from app.evaluation.retrieval_ranking_real_schemas import (
    FrozenRankingArtifact,
    RankingHardLimits,
    RankingPricingSnapshot,
    RetrievalRankingRunPlan,
)
from app.evaluation.runner import calculate_evaluation_checksum
from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.evaluation.validation import validate_evaluation_set

FROZEN_ARTIFACTS = (
    ("baseline", "reports/current_baseline_v1.json", "598952a8772fde26eac428cdad0335f889241f61d12b9c55bfabed5329a26ed5"),
    ("human_review", "reports/human_review_capture_v1.json", "db4a9afc6ed4404a17512dcf5ac39017bf3fb64cf6b8da06dc874c416b6f0a84"),
    ("rag_v1_2_comparison", "reports/rag_v1_2_real_comparison_v1.json", "f54e86a1b39518d998e861c101b225b160188d373488bca4fa821913c09e2893"),
    ("ranking_mock", "reports/retrieval_ranking_mock_v1.json", "2ca18667421937937247ebd40d502fda9d07e884a026e1795017d86e9d12f773"),
)
INVALID_ATTEMPT_PATH = "reports/retrieval_ranking_real_v1_invalid_vector_port_20260721.json"
INVALID_ATTEMPT_SHA256 = "e2396f97ca5f5f6e89c2bfb9c6e53a5e9ec064ce2135371c928a4028836acd5c"


@dataclass(frozen=True)
class RankingPreflightReport:
    case_count: int
    chroma_chunk_count: int
    current_corpus_snapshot_checked: bool
    frozen_artifacts_checked: bool
    candidate_configuration_checked: bool
    production_flags_disabled: bool
    remote_credentials_checked: bool
    remote_connectivity_checked: bool
    max_embedding_calls: int
    max_keyword_scans: int
    max_rerank_calls: int
    max_answer_calls: int
    max_total_tokens: int
    max_estimated_cost_cny: float


def build_retrieval_ranking_plan(
    *, evaluation_set: EvaluationSet, corpus: CorpusManifest, category_config: dict
) -> RetrievalRankingRunPlan:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    return RetrievalRankingRunPlan(
        schema_version="retrieval_ranking_plan_v1",
        plan_version="retrieval_ranking_preflight_v1",
        generated_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=corpus.corpus_version,
        corpus_checksum=corpus.corpus_checksum,
        frozen_artifacts=[
            FrozenRankingArtifact(role=role, relative_path=path, sha256=digest)
            for role, path, digest in FROZEN_ARTIFACTS
        ],
        candidate_profiles=build_retrieval_ranking_profiles(),
        hard_limits=RankingHardLimits(
            max_cases=40,
            max_embedding_calls=40,
            max_keyword_scans=40,
            max_rerank_calls=40,
            max_answer_calls=0,
            automatic_retries=0,
            embedding_tokens_reserved_per_call=512,
            rerank_tokens_reserved_per_call=30000,
            max_total_tokens=1220480,
            max_estimated_cost_cny=1.1,
            stop_conditions=[
                "任何下一次付费调用超过调用、Token或费用上限前立即停止",
                "成功调用缺少Token或费用计量时立即停止",
                "计划哈希、冻结产物、eval_v1或corpus_v1不一致时禁止开始",
                "正式输出已存在时禁止覆盖",
            ],
        ),
        pricing=RankingPricingSnapshot(
            verified_on="2026-07-20",
            deployment_scope="中国内地",
            official_pricing_url="https://help.aliyun.com/zh/model-studio/model-pricing",
            official_rerank_limits_url="https://help.aliyun.com/en/model-studio/rerank",
            embedding_model="text-embedding-v4",
            embedding_price_per_million_tokens_cny=0.5,
            rerank_model="gte-rerank-v2",
            rerank_price_per_million_tokens_cny=0.8,
            expected_cost_min_cny=0.2,
            expected_cost_max_cny=0.6,
        ),
        prior_attempt_estimated_cost_cny=0.0,
        cumulative_hard_ceiling_cny=1.1,
        paid_execution_available=True,
        requires_new_user_confirmation=True,
        production_flags_changed=False,
    )


def build_retrieval_ranking_recovery_plan(
    *, evaluation_set: EvaluationSet, corpus: CorpusManifest, category_config: dict
) -> RetrievalRankingRunPlan:
    original = build_retrieval_ranking_plan(
        evaluation_set=evaluation_set, corpus=corpus, category_config=category_config
    )
    return original.model_copy(
        update={
            "plan_version": "retrieval_ranking_recovery_preflight_v2",
            "generated_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
            "frozen_artifacts": [
                *original.frozen_artifacts,
                FrozenRankingArtifact(
                    role="invalid_vector_port_attempt",
                    relative_path=INVALID_ATTEMPT_PATH,
                    sha256=INVALID_ATTEMPT_SHA256,
                ),
            ],
            "prior_attempt_estimated_cost_cny": 0.20761,
            "cumulative_hard_ceiling_cny": 1.31,
        }
    )


def run_full_ranking_preflight(
    *,
    plan: RetrievalRankingRunPlan,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    settings: Settings,
    evaluation_root: Path,
    current_manifest_reader: Callable[[str], CorpusManifest],
    collection_count_reader: Callable[[Settings], int] = read_chroma_collection_count,
) -> RankingPreflightReport:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    builder = (
        build_retrieval_ranking_recovery_plan
        if plan.plan_version == "retrieval_ranking_recovery_preflight_v2"
        else build_retrieval_ranking_plan
    )
    expected_plan = builder(
        evaluation_set=evaluation_set, corpus=corpus, category_config=category_config
    )
    if plan != expected_plan:
        raise ValueError("versioned ranking plan differs from the frozen plan contract")
    if len(evaluation_set.cases) != plan.hard_limits.max_cases:
        raise ValueError("evaluation case count does not match the plan")
    if plan.evaluation_checksum != calculate_evaluation_checksum(evaluation_set):
        raise ValueError("eval_v1 checksum does not match the plan")
    if plan.corpus_checksum != corpus.corpus_checksum:
        raise ValueError("corpus_v1 checksum does not match the plan")
    for artifact in plan.frozen_artifacts:
        content = (evaluation_root / artifact.relative_path).read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise ValueError(f"frozen artifact hash mismatch: {artifact.relative_path}")
    if current_manifest_reader(corpus.generated_on) != corpus:
        raise ValueError("current MySQL/files/Chroma snapshot differs from corpus_v1")
    count = collection_count_reader(settings)
    if count != corpus.chunk_count:
        raise ValueError("current Chroma chunk count differs from corpus_v1")
    if settings.rag_hybrid_search_enabled or settings.rag_rerank_enabled:
        raise ValueError("production ranking experiment flags must remain disabled")
    if any(value is not None for value in (
        settings.rag_min_relevance_score, settings.rag_filter_department,
        settings.rag_filter_topic, settings.rag_filter_document_type,
        settings.rag_filter_knowledge_base_version,
    )):
        raise ValueError("production filters and relevance threshold must remain disabled")
    defaults = plan.candidate_profiles[0].configuration
    actual = (
        settings.embedding_model_name, settings.chroma_collection_name,
        settings.rag_hybrid_vector_weight, settings.rag_hybrid_keyword_weight,
        settings.rag_hybrid_rrf_k, settings.rag_rerank_model_name,
    )
    planned = (
        plan.pricing.embedding_model,
        corpus.chroma_collection, defaults.vector_weight,
        defaults.keyword_weight, defaults.rrf_k, defaults.rerank_model,
    )
    if actual != planned:
        raise ValueError("current retrieval configuration differs from the plan")
    settings.require_dashscope_api_key()
    limits = plan.hard_limits
    return RankingPreflightReport(
        case_count=len(evaluation_set.cases), chroma_chunk_count=count,
        current_corpus_snapshot_checked=True, frozen_artifacts_checked=True,
        candidate_configuration_checked=True, production_flags_disabled=True,
        remote_credentials_checked=True, remote_connectivity_checked=False,
        max_embedding_calls=limits.max_embedding_calls,
        max_keyword_scans=limits.max_keyword_scans,
        max_rerank_calls=limits.max_rerank_calls,
        max_answer_calls=limits.max_answer_calls,
        max_total_tokens=limits.max_total_tokens,
        max_estimated_cost_cny=limits.max_estimated_cost_cny,
    )
