"""可关闭、有预算边界且失败回退的RAG重排阶段。"""

import logging

from app.core.config import Settings
from app.infrastructure.reranker import DashScopeRerankAdapter
from app.modules.rag.policies import RerankPolicy
from app.modules.rag.ports import RerankPort, RetrievedChunk

logger = logging.getLogger(__name__)


class RerankStage:
    """在召回后执行至多一次重排，任何失败都保留原候选顺序。"""

    def __init__(self, reranker: RerankPort | None, policy: RerankPolicy) -> None:
        if policy.enabled and reranker is None:
            raise ValueError("启用重排时必须提供RerankPort")
        self.reranker = reranker
        self.policy = policy

    def apply(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not self.policy.enabled or not chunks:
            return chunks

        candidates = chunks[: self.policy.max_candidates]
        top_n = min(max(top_k, 0), len(candidates))
        if top_n == 0:
            return chunks
        reserved_tokens = self.policy.estimate_input_tokens(query, candidates)
        reserved_cost = self.policy.estimate_cost_cny(reserved_tokens)
        if (
            reserved_tokens > self.policy.max_input_tokens
            or reserved_cost > self.policy.max_estimated_cost_cny
        ):
            logger.warning(
                "重排输入超过预算，已保留原候选顺序",
                extra={"reason": "budget_exceeded"},
            )
            return chunks

        try:
            result = self.reranker.rerank(query, candidates, top_n)  # type: ignore[union-attr]
            if result.usage.request_count != 1:
                raise ValueError("重排调用计量不符合单次调用约束")
            if result.usage.input_tokens > self.policy.max_input_tokens:
                raise ValueError("重排实际Token超过配置上限")
            if result.usage.estimated_cost_cny > self.policy.max_estimated_cost_cny:
                raise ValueError("重排实际费用超过配置上限")
            candidate_ids = {id(candidate) for candidate in candidates}
            if len(result.chunks) != top_n or any(
                id(chunk) not in candidate_ids for chunk in result.chunks
            ):
                raise ValueError("重排结果未保持候选边界")
            return result.chunks
        except Exception as exc:
            logger.warning(
                "重排失败，已保留原候选顺序",
                extra={"error_type": type(exc).__name__},
            )
            return chunks


def create_current_rerank_stage(settings: Settings) -> RerankStage:
    """默认关闭时不创建厂商适配器；开启时再延迟读取密钥。"""
    policy = RerankPolicy.from_settings(settings)
    if not policy.enabled:
        return RerankStage(None, policy)
    adapter = DashScopeRerankAdapter(
        api_key=settings.require_dashscope_api_key(),
        model_name=policy.model_name,
        timeout_seconds=policy.timeout_seconds,
        input_price_per_million_tokens_cny=(
            policy.input_price_per_million_tokens_cny
        ),
    )
    return RerankStage(adapter, policy)
