"""任务7.6真实候选对比前的纯本地计划校验。"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.evaluation.comparison import build_candidate_profiles
from app.evaluation.comparison_schemas import (
    ComparisonHardLimits,
    ComparisonPricingSnapshot,
    ComparisonRunPlan,
    FrozenComparisonArtifact,
)
from app.evaluation.report_schemas import BaselineReport
from app.evaluation.runner import calculate_evaluation_checksum
from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.evaluation.validation import validate_evaluation_set
from app.evaluation.preflight import read_chroma_collection_count

FROZEN_BASELINE_SHA256 = (
    "598952a8772fde26eac428cdad0335f889241f61d12b9c55bfabed5329a26ed5"
)
FROZEN_HUMAN_CAPTURE_SHA256 = (
    "db4a9afc6ed4404a17512dcf5ac39017bf3fb64cf6b8da06dc874c416b6f0a84"
)


@dataclass(frozen=True)
class FullComparisonPreflightReport:
    dataset_version: str
    corpus_version: str
    corpus_checksum: str
    case_count: int
    chroma_collection: str
    chroma_chunk_count: int
    current_corpus_snapshot_checked: bool
    candidate_configuration_checked: bool
    production_flags_disabled: bool
    remote_credentials_checked: bool
    remote_connectivity_checked: bool
    automatic_retries: int
    max_embedding_calls: int
    max_answer_calls: int
    max_rerank_calls: int
    max_total_tokens: int
    max_estimated_cost_cny: float
    expected_cost_min_cny: float
    expected_cost_max_cny: float


def _read_frozen_report(
    path: Path,
    *,
    expected_sha256: str,
    evaluation_set: EvaluationSet,
) -> BaselineReport:
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"冻结评估产物哈希不一致：{path.name}")
    report = BaselineReport.model_validate_json(content)
    if (
        report.dataset_version != evaluation_set.dataset_version
        or report.evaluation_checksum
        != calculate_evaluation_checksum(evaluation_set)
        or report.corpus_version != evaluation_set.corpus_version
        or report.corpus_checksum != evaluation_set.corpus_checksum
    ):
        raise ValueError(f"冻结评估产物未绑定当前eval_v1：{path.name}")
    return report


def build_comparison_run_plan(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    baseline_path: Path,
    human_capture_path: Path,
) -> ComparisonRunPlan:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    _read_frozen_report(
        baseline_path,
        expected_sha256=FROZEN_BASELINE_SHA256,
        evaluation_set=evaluation_set,
    )
    _read_frozen_report(
        human_capture_path,
        expected_sha256=FROZEN_HUMAN_CAPTURE_SHA256,
        evaluation_set=evaluation_set,
    )
    profiles = build_candidate_profiles()
    return ComparisonRunPlan(
        schema_version="rag_comparison_plan_v1",
        plan_version="rag_v1_2_preflight_v1",
        generated_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        dataset_version=evaluation_set.dataset_version,
        evaluation_checksum=calculate_evaluation_checksum(evaluation_set),
        corpus_version=evaluation_set.corpus_version,
        corpus_checksum=evaluation_set.corpus_checksum,
        frozen_artifacts=[
            FrozenComparisonArtifact(
                role="baseline",
                relative_path="reports/current_baseline_v1.json",
                sha256=FROZEN_BASELINE_SHA256,
            ),
            FrozenComparisonArtifact(
                role="human_review_capture",
                relative_path="reports/human_review_capture_v1.json",
                sha256=FROZEN_HUMAN_CAPTURE_SHA256,
            ),
        ],
        baseline_candidate_id="vector_baseline_v1",
        new_candidate_ids=["hybrid_rrf_v1", "hybrid_rrf_rerank_v1"],
        candidate_profiles=profiles,
        hard_limits=ComparisonHardLimits(
            max_cases_per_new_candidate=40,
            new_candidate_run_count=2,
            max_embedding_calls=80,
            max_answer_calls=80,
            max_rerank_calls=40,
            automatic_retries=0,
            max_total_tokens=1_480_000,
            max_estimated_cost_cny=4.4,
            stop_conditions=[
                "任一调用次数达到上限前停止",
                "下一次调用的Token预留会超过总上限时停止",
                "下一次调用的费用预留会超过总上限时停止",
                "成功返回的付费调用缺失Token或费用计量时停止；失败调用保留最坏预留",
                "冻结报告、eval_v1或corpus_v1校验不一致时禁止开始",
            ],
        ),
        pricing=ComparisonPricingSnapshot(
            verified_on="2026-07-19",
            deployment_scope="中国内地",
            official_pricing_url=(
                "https://help.aliyun.com/zh/model-studio/model-pricing"
            ),
            qwen_model="qwen3-max",
            qwen_input_price_per_million_tokens_cny=2.5,
            qwen_output_price_per_million_tokens_cny=10.0,
            embedding_model="text-embedding-v4",
            embedding_price_per_million_tokens_cny=0.5,
            rerank_model="gte-rerank-v2",
            rerank_price_per_million_tokens_cny=0.8,
            expected_cost_min_cny=0.6,
            expected_cost_max_cny=1.0,
        ),
        paid_execution_available=True,
        requires_new_user_confirmation=True,
        production_flags_changed=False,
    )


def run_full_comparison_preflight(
    *,
    plan: ComparisonRunPlan,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    settings: Settings,
    current_manifest_reader: Callable[[str], CorpusManifest],
    collection_count_reader: Callable[[Settings], int] = read_chroma_collection_count,
) -> FullComparisonPreflightReport:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    if len(evaluation_set.cases) != plan.hard_limits.max_cases_per_new_candidate:
        raise ValueError("评估题数与候选运行计划不一致")
    current_manifest = current_manifest_reader(corpus.generated_on)
    if current_manifest != corpus:
        raise ValueError("corpus_v1 与当前MySQL、文件或Chroma快照不一致")
    chunk_count = collection_count_reader(settings)
    if chunk_count != corpus.chunk_count:
        raise ValueError("当前Chroma片段数与corpus_v1不一致")
    if settings.rag_hybrid_search_enabled or settings.rag_rerank_enabled:
        raise ValueError("生产RAG优化开关必须保持关闭")
    if any(
        value is not None
        for value in (
            settings.rag_min_relevance_score,
            settings.rag_filter_department,
            settings.rag_filter_topic,
            settings.rag_filter_document_type,
            settings.rag_filter_knowledge_base_version,
        )
    ):
        raise ValueError("候选对比要求过滤和最低相关度保持关闭")
    profile = plan.candidate_profiles[0].configuration
    retrieval = profile.retrieval
    rerank = profile.rerank
    answer = profile.answer
    actual_values = (
        settings.embedding_model_name,
        settings.chroma_collection_name,
        settings.chat_model_name,
        settings.rag_hybrid_vector_weight,
        settings.rag_hybrid_keyword_weight,
        settings.rag_hybrid_rrf_k,
        settings.rag_rerank_model_name,
        settings.rag_rerank_max_candidates,
        settings.rag_rerank_timeout_seconds,
        settings.rag_rerank_max_input_tokens,
        settings.rag_rerank_input_price_per_million_tokens_cny,
        settings.rag_rerank_max_estimated_cost_cny,
    )
    planned_values = (
        retrieval.embedding_model,
        retrieval.chroma_collection,
        answer.model,
        retrieval.vector_weight,
        retrieval.keyword_weight,
        retrieval.rrf_k,
        rerank.model,
        rerank.max_candidates,
        rerank.timeout_seconds,
        rerank.max_input_tokens,
        rerank.input_price_per_million_tokens_cny,
        rerank.max_estimated_cost_cny,
    )
    if actual_values != planned_values:
        raise ValueError("当前RAG配置与候选配置指纹不一致")
    settings.require_dashscope_api_key()
    limits = plan.hard_limits
    pricing = plan.pricing
    return FullComparisonPreflightReport(
        dataset_version=evaluation_set.dataset_version,
        corpus_version=corpus.corpus_version,
        corpus_checksum=corpus.corpus_checksum,
        case_count=len(evaluation_set.cases),
        chroma_collection=settings.chroma_collection_name,
        chroma_chunk_count=chunk_count,
        current_corpus_snapshot_checked=True,
        candidate_configuration_checked=True,
        production_flags_disabled=True,
        remote_credentials_checked=True,
        remote_connectivity_checked=False,
        automatic_retries=limits.automatic_retries,
        max_embedding_calls=limits.max_embedding_calls,
        max_answer_calls=limits.max_answer_calls,
        max_rerank_calls=limits.max_rerank_calls,
        max_total_tokens=limits.max_total_tokens,
        max_estimated_cost_cny=limits.max_estimated_cost_cny,
        expected_cost_min_cny=pricing.expected_cost_min_cny,
        expected_cost_max_cny=pricing.expected_cost_max_cny,
    )
