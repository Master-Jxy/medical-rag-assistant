"""真实基线运行前的只读检查，不调用模型或 Embedding。"""

from collections.abc import Callable
from dataclasses import dataclass

import chromadb

from app.core.config import Settings
from app.evaluation.budget import EvaluationBudgetLimits
from app.evaluation.current_adapters import (
    EVALUATION_MAX_RETRIES,
    FROZEN_TOP_K,
)
from app.evaluation.schemas import CorpusManifest, EvaluationSet
from app.evaluation.validation import validate_evaluation_set
from app.schemas.chat import ChatRequest

MAX_REAL_EVALUATION_CASES = 40


@dataclass(frozen=True)
class EvaluationPreflightReport:
    dataset_version: str
    corpus_version: str
    corpus_checksum: str
    case_count: int
    chroma_collection: str
    chroma_chunk_count: int
    chat_model: str
    embedding_model: str
    top_k: int
    max_retries: int
    remote_credentials_checked: bool
    corpus_snapshot_checked: bool
    remote_connectivity_checked: bool = False


def read_chroma_collection_count(settings: Settings) -> int:
    """只读取集合数量；不会创建集合，也不会触发查询向量化。"""
    client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
    collection = client.get_collection(settings.chroma_collection_name)
    return collection.count()


def run_preflight(
    *,
    evaluation_set: EvaluationSet,
    corpus: CorpusManifest,
    category_config: dict,
    settings: Settings,
    budget_limits: EvaluationBudgetLimits,
    collection_count_reader: Callable[[Settings], int] = read_chroma_collection_count,
    current_manifest_reader: Callable[[str], CorpusManifest] | None = None,
) -> EvaluationPreflightReport:
    validate_evaluation_set(evaluation_set, corpus, category_config)
    if len(evaluation_set.cases) > MAX_REAL_EVALUATION_CASES:
        raise ValueError("真实评估最多允许 40 题")
    if budget_limits.max_retrieval_calls > MAX_REAL_EVALUATION_CASES:
        raise ValueError("检索调用硬上限不能超过 40")
    if budget_limits.max_model_calls > MAX_REAL_EVALUATION_CASES:
        raise ValueError("模型调用硬上限不能超过 40")
    if EVALUATION_MAX_RETRIES != 0:
        raise ValueError("真实评估必须关闭自动重试")
    current_top_k = int(ChatRequest.model_fields["top_k"].default)
    if current_top_k != FROZEN_TOP_K:
        raise ValueError("评估 top_k 与当前 RAG 默认值不一致")
    if settings.chroma_collection_name != corpus.chroma_collection:
        raise ValueError("Chroma 集合名与 corpus_v1 不一致")
    if settings.chunk_size != corpus.chunk_size or settings.chunk_overlap != corpus.chunk_overlap:
        raise ValueError("切片配置与 corpus_v1 不一致")
    if not settings.chat_model_name.strip() or not settings.embedding_model_name.strip():
        raise ValueError("模型名称未配置")
    settings.require_dashscope_api_key()
    if current_manifest_reader is not None:
        current_manifest = current_manifest_reader(corpus.generated_on)
        if current_manifest != corpus:
            raise ValueError("corpus_v1 与当前 MySQL 文档登记、文件或 Chroma 不一致")
    chunk_count = collection_count_reader(settings)
    if chunk_count != corpus.chunk_count:
        raise ValueError(
            f"Chroma 片段数与 corpus_v1 不一致：{chunk_count} != {corpus.chunk_count}"
        )
    return EvaluationPreflightReport(
        dataset_version=evaluation_set.dataset_version,
        corpus_version=corpus.corpus_version,
        corpus_checksum=corpus.corpus_checksum,
        case_count=len(evaluation_set.cases),
        chroma_collection=settings.chroma_collection_name,
        chroma_chunk_count=chunk_count,
        chat_model=settings.chat_model_name,
        embedding_model=settings.embedding_model_name,
        top_k=FROZEN_TOP_K,
        max_retries=EVALUATION_MAX_RETRIES,
        remote_credentials_checked=True,
        corpus_snapshot_checked=current_manifest_reader is not None,
    )
