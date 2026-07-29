import asyncio
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.model_factory import create_chat_model, create_embedding_model
from app.infrastructure.async_chat_model import DashScopeAsyncChatModel
from app.modules.rag.ports import TokenMeasurement


def test_online_model_factories_use_configured_zero_retries(monkeypatch) -> None:
    chat_factory = Mock(return_value=Mock())
    embedding_factory = Mock(return_value=Mock())
    monkeypatch.setattr("app.core.model_factory.ChatTongyi", chat_factory)
    monkeypatch.setattr(
        "app.core.model_factory.DashScopeEmbeddings", embedding_factory
    )
    settings = Settings(
        _env_file=None,
        dashscope_api_key="test-key",
        dashscope_max_retries=0,
    )

    create_chat_model(settings)
    create_embedding_model(settings)

    assert chat_factory.call_args.kwargs["max_retries"] == 0
    assert embedding_factory.call_args.kwargs["max_retries"] == 0


def test_online_model_retry_default_environment_override_and_bounds_are_explicit(
    monkeypatch,
) -> None:
    assert Settings(_env_file=None).dashscope_max_retries == 2
    monkeypatch.setenv("DASHSCOPE_MAX_RETRIES", "0")
    assert Settings(_env_file=None).dashscope_max_retries == 0

    with pytest.raises(ValidationError):
        Settings(_env_file=None, dashscope_max_retries=-1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, dashscope_max_retries=11)


def test_async_sse_model_failure_is_not_retried_when_config_is_zero(
    monkeypatch,
) -> None:
    vendor_call = AsyncMock(side_effect=TimeoutError("fixed timeout"))
    monkeypatch.setattr(
        "app.infrastructure.async_chat_model.AioGeneration.call", vendor_call
    )
    model = DashScopeAsyncChatModel(
        Settings(
            _env_file=None,
            dashscope_api_key="test-key",
            dashscope_max_retries=0,
        )
    )

    async def consume() -> None:
        async for _ in model.stream([{"role": "user", "content": "测试"}]):
            pass

    with pytest.raises(TimeoutError, match="fixed timeout"):
        asyncio.run(consume())

    assert vendor_call.await_count == 1


def test_async_sse_model_emits_late_vendor_usage_without_fabrication(
    monkeypatch,
) -> None:
    async def responses():
        yield SimpleNamespace(
            status_code=HTTPStatus.OK,
            output={"choices": [{"message": {"content": "回答"}}]},
            usage=None,
        )
        yield SimpleNamespace(
            status_code=HTTPStatus.OK,
            output={"choices": []},
            usage={"input_tokens": 21, "output_tokens": 5, "total_tokens": 26},
        )

    monkeypatch.setattr(
        "app.infrastructure.async_chat_model.AioGeneration.call",
        AsyncMock(return_value=responses()),
    )
    model = DashScopeAsyncChatModel(
        Settings(_env_file=None, dashscope_api_key="test-key")
    )

    async def consume():
        return [
            chunk
            async for chunk in model.stream(
                [{"role": "user", "content": "测试"}]
            )
        ]

    chunks = asyncio.run(consume())

    assert [chunk.content for chunk in chunks] == ["回答", ""]
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.measurement is TokenMeasurement.ACTUAL
    assert chunks[-1].usage.input_tokens == 21
    assert chunks[-1].usage.output_tokens == 5


def test_async_sse_model_marks_missing_vendor_usage_unknown(monkeypatch) -> None:
    async def responses():
        yield SimpleNamespace(
            status_code=HTTPStatus.OK,
            output={"choices": [{"message": {"content": "回答"}}]},
            usage=None,
        )

    monkeypatch.setattr(
        "app.infrastructure.async_chat_model.AioGeneration.call",
        AsyncMock(return_value=responses()),
    )
    model = DashScopeAsyncChatModel(
        Settings(_env_file=None, dashscope_api_key="test-key")
    )

    async def consume():
        return [
            chunk
            async for chunk in model.stream(
                [{"role": "user", "content": "测试"}]
            )
        ]

    chunks = asyncio.run(consume())

    assert chunks[-1].content == ""
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.measurement is TokenMeasurement.UNKNOWN
