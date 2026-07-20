"""DashScope 文本重排基础设施适配器。"""

from http import HTTPStatus
from typing import Callable

from dashscope import TextReRank

from app.modules.rag.ports import (
    RerankResult,
    RerankUsage,
    RetrievedChunk,
)


class DashScopeRerankAdapter:
    """只把厂商响应映射为RAG端口对象，不决定业务回退策略。"""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        input_price_per_million_tokens_cny: float,
        call: Callable[..., object] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.input_price_per_million_tokens_cny = (
            input_price_per_million_tokens_cny
        )
        self._call = call or TextReRank.call

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_n: int,
    ) -> RerankResult:
        response = self._call(
            model=self.model_name,
            query=query,
            documents=[candidate.content for candidate in candidates],
            return_documents=False,
            top_n=top_n,
            api_key=self.api_key,
            request_timeout=self.timeout_seconds,
        )
        if getattr(response, "status_code", None) != HTTPStatus.OK:
            raise RuntimeError("重排服务调用失败")

        raw_results = getattr(getattr(response, "output", None), "results", None)
        if not isinstance(raw_results, list):
            raise ValueError("重排服务未返回有效结果")
        ranked: list[RetrievedChunk] = []
        seen_indexes: set[int] = set()
        for item in raw_results:
            index = getattr(item, "index", None)
            if not isinstance(index, int) or not 0 <= index < len(candidates):
                raise ValueError("重排结果包含无效候选索引")
            if index in seen_indexes:
                raise ValueError("重排结果包含重复候选索引")
            seen_indexes.add(index)
            ranked.append(candidates[index])
        if len(ranked) != top_n:
            raise ValueError("重排结果数量与请求不一致")

        total_tokens = getattr(getattr(response, "usage", None), "total_tokens", 0)
        if not isinstance(total_tokens, int) or total_tokens < 0:
            raise ValueError("重排服务未返回有效Token计量")
        return RerankResult(
            chunks=ranked,
            usage=RerankUsage(
                request_count=1,
                input_tokens=total_tokens,
                estimated_cost_cny=(
                    total_tokens
                    * self.input_price_per_million_tokens_cny
                    / 1_000_000
                ),
            ),
        )
