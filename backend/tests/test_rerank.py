import asyncio
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.infrastructure.reranker import DashScopeRerankAdapter
from app.modules.rag.policies import RerankPolicy
from app.modules.rag.ports import (
    RerankResult,
    RerankUsage,
    RetrievedChunk,
)
from app.modules.rag.rerank import RerankStage, create_current_rerank_stage
from app.services.rag_service import RagService


def make_chunk(index: int, content: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        content=content or f"片段{index}",
        file_name=f"资料{index}.txt",
        page=index,
        chunk_id=f"chunk-{index}",
    )


class FixedReranker:
    def __init__(
        self,
        order: list[int] | None = None,
        error: Exception | None = None,
        usage: RerankUsage | None = None,
    ) -> None:
        self.order = order
        self.error = error
        self.usage = usage or RerankUsage(1, 100, 0.00008)
        self.calls = []

    def rerank(self, query, candidates, top_n):
        self.calls.append((query, candidates, top_n))
        if self.error:
            raise self.error
        order = self.order or list(reversed(range(top_n)))
        return RerankResult(
            chunks=[candidates[index] for index in order],
            usage=self.usage,
        )


class FixedQueryBuilder:
    def build(self, question, history):
        return "脱敏检索查询"


class FixedSearch:
    def __init__(self, chunks):
        self.chunks = chunks

    def search(self, query, top_k):
        return self.chunks


class CapturingAnswer:
    def __init__(self):
        self.received = []

    def answer(self, question, history, chunks):
        self.received.append(chunks)
        return "回答"

    def stream_answer(self, question, history, chunks) -> Iterator[str]:
        self.received.append(chunks)
        yield "回答"

    async def astream_answer(self, question, history, chunks) -> AsyncIterator[str]:
        self.received.append(chunks)
        yield "回答"


def enabled_policy(**overrides) -> RerankPolicy:
    values = {
        "enabled": True,
        "max_candidates": 10,
        "max_input_tokens": 12000,
        "input_price_per_million_tokens_cny": 0.8,
        "max_estimated_cost_cny": 0.01,
    }
    values.update(overrides)
    return RerankPolicy(**values)


def test_disabled_stage_keeps_order_without_calling_reranker() -> None:
    chunks = [make_chunk(1), make_chunk(2)]
    reranker = FixedReranker()
    stage = RerankStage(reranker, RerankPolicy(enabled=False))

    assert stage.apply("查询", chunks, 2) is chunks
    assert reranker.calls == []


def test_enabled_stage_limits_candidates_and_calls_only_once() -> None:
    chunks = [make_chunk(index) for index in range(1, 6)]
    reranker = FixedReranker(order=[2, 1, 0])
    stage = RerankStage(reranker, enabled_policy(max_candidates=3))

    result = stage.apply("查询", chunks, 4)

    assert [chunk.chunk_id for chunk in result] == ["chunk-3", "chunk-2", "chunk-1"]
    assert len(reranker.calls) == 1
    assert reranker.calls[0][1] == chunks[:3]
    assert reranker.calls[0][2] == 3


def test_budget_exceeded_skips_paid_call_and_keeps_original_order(monkeypatch) -> None:
    import app.modules.rag.rerank as rerank_module

    logged = []
    monkeypatch.setattr(
        rerank_module.logger,
        "warning",
        lambda message, **kwargs: logged.append((message, kwargs)),
    )
    chunks = [make_chunk(1, "很长的内容" * 20)]
    reranker = FixedReranker()
    stage = RerankStage(
        reranker,
        enabled_policy(max_input_tokens=10, max_estimated_cost_cny=1),
    )

    result = stage.apply("敏感问题正文", chunks, 1)

    assert result is chunks
    assert reranker.calls == []
    assert "敏感问题正文" not in repr(logged)
    assert "很长的内容" not in repr(logged)
    assert logged == [
        ("重排输入超过预算，已保留原候选顺序", {"extra": {"reason": "budget_exceeded"}})
    ]


@pytest.mark.parametrize(
    "error",
    [TimeoutError("secret"), RuntimeError("vendor secret")],
)
def test_timeout_or_failure_falls_back_without_logging_content(
    error, monkeypatch
) -> None:
    import app.modules.rag.rerank as rerank_module

    logged = []
    monkeypatch.setattr(
        rerank_module.logger,
        "warning",
        lambda message, **kwargs: logged.append((message, kwargs)),
    )
    chunks = [make_chunk(1), make_chunk(2)]
    reranker = FixedReranker(error=error)
    stage = RerankStage(reranker, enabled_policy())

    result = stage.apply("用户问题不能记录", chunks, 2)

    assert result is chunks
    assert len(reranker.calls) == 1
    assert "用户问题不能记录" not in repr(logged)
    assert "secret" not in repr(logged)
    assert logged == [
        (
            "重排失败，已保留原候选顺序",
            {"extra": {"error_type": type(error).__name__}},
        )
    ]


def test_invalid_usage_or_foreign_chunk_falls_back() -> None:
    chunks = [make_chunk(1), make_chunk(2)]
    foreign = make_chunk(9)

    class InvalidReranker:
        def rerank(self, query, candidates, top_n):
            return RerankResult(
                chunks=[foreign, candidates[0]],
                usage=RerankUsage(2, 1, 0),
            )

    stage = RerankStage(InvalidReranker(), enabled_policy())

    assert stage.apply("查询", chunks, 2) is chunks


def test_rag_three_entrypoints_use_same_reranked_order() -> None:
    original = [make_chunk(1), make_chunk(2)]
    reranker = FixedReranker(order=[1, 0])
    answer = CapturingAnswer()
    service = RagService(
        FixedQueryBuilder(),
        FixedSearch(original),
        answer,
        rerank_stage=RerankStage(reranker, enabled_policy()),
    )

    _, sources = service.ask("问题", 2)
    stream_sources = list(service.stream_ask("问题", 2))[-1]["data"]["sources"]

    async def collect_async():
        return [event async for event in service.astream_ask("问题", 2)]

    async_sources = asyncio.run(collect_async())[-1]["data"]["sources"]

    assert [chunks[0].chunk_id for chunks in answer.received] == [
        "chunk-2",
        "chunk-2",
        "chunk-2",
    ]
    assert [source.file_name for source in sources] == ["资料2.txt", "资料1.txt"]
    assert [source["file_name"] for source in stream_sources] == [
        "资料2.txt",
        "资料1.txt",
    ]
    assert [source["file_name"] for source in async_sources] == [
        "资料2.txt",
        "资料1.txt",
    ]
    assert len(reranker.calls) == 3


def test_dashscope_adapter_maps_response_and_passes_bounded_timeout_once() -> None:
    calls = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                results=[
                    SimpleNamespace(index=1, relevance_score=0.9),
                    SimpleNamespace(index=0, relevance_score=0.6),
                ]
            ),
            usage=SimpleNamespace(total_tokens=250),
        )

    chunks = [make_chunk(1), make_chunk(2)]
    adapter = DashScopeRerankAdapter(
        api_key="not-a-real-key",
        model_name="gte-rerank-v2",
        timeout_seconds=2.5,
        input_price_per_million_tokens_cny=0.8,
        call=fake_call,
    )

    result = adapter.rerank("查询", chunks, 2)

    assert len(calls) == 1
    assert calls[0] == {
        "model": "gte-rerank-v2",
        "query": "查询",
        "documents": ["片段1", "片段2"],
        "return_documents": False,
        "top_n": 2,
        "api_key": "not-a-real-key",
        "request_timeout": 2.5,
    }
    assert result.chunks == [chunks[1], chunks[0]]
    assert result.usage == RerankUsage(1, 250, 0.0002)


def test_dashscope_adapter_rejects_failed_or_malformed_response() -> None:
    chunks = [make_chunk(1)]
    failed = DashScopeRerankAdapter(
        api_key="key",
        model_name="gte-rerank-v2",
        timeout_seconds=1,
        input_price_per_million_tokens_cny=0.8,
        call=lambda **kwargs: SimpleNamespace(status_code=500),
    )
    duplicate = DashScopeRerankAdapter(
        api_key="key",
        model_name="gte-rerank-v2",
        timeout_seconds=1,
        input_price_per_million_tokens_cny=0.8,
        call=lambda **kwargs: SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(
                results=[
                    SimpleNamespace(index=0),
                    SimpleNamespace(index=0),
                ]
            ),
            usage=SimpleNamespace(total_tokens=1),
        ),
    )
    missing_usage = DashScopeRerankAdapter(
        api_key="key",
        model_name="gte-rerank-v2",
        timeout_seconds=1,
        input_price_per_million_tokens_cny=0.8,
        call=lambda **kwargs: SimpleNamespace(
            status_code=HTTPStatus.OK,
            output=SimpleNamespace(results=[SimpleNamespace(index=0)]),
            usage=SimpleNamespace(total_tokens=None),
        ),
    )

    with pytest.raises(RuntimeError, match="调用失败"):
        failed.rerank("查询", chunks, 1)
    with pytest.raises(ValueError, match="重复候选"):
        duplicate.rerank("查询", chunks * 2, 2)
    with pytest.raises(ValueError, match="Token计量"):
        missing_usage.rerank("查询", chunks, 1)


def test_default_factory_does_not_create_vendor_adapter(monkeypatch) -> None:
    import app.modules.rag.rerank as rerank_module

    def forbidden_adapter(**kwargs):
        raise AssertionError("默认关闭时不应创建厂商适配器")

    monkeypatch.setattr(rerank_module, "DashScopeRerankAdapter", forbidden_adapter)

    stage = create_current_rerank_stage(Settings(_env_file=None))

    assert stage.policy.enabled is False
    assert stage.reranker is None


def test_enabled_factory_requires_key_and_settings_are_bounded() -> None:
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        create_current_rerank_stage(
            Settings(
                _env_file=None,
                dashscope_api_key=None,
                rag_rerank_enabled=True,
            )
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_rerank_timeout_seconds=31)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_rerank_max_candidates=0)
