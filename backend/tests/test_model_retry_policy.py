import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.model_factory import create_chat_model, create_embedding_model
from app.infrastructure.async_chat_model import DashScopeAsyncChatModel


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
