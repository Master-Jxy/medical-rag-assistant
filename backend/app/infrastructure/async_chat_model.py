"""可取消的 DashScope 异步流式聊天适配器。"""

from collections.abc import AsyncIterator, Mapping
from http import HTTPStatus

from dashscope.aigc.generation import AioGeneration

from app.core.config import Settings, get_settings
from app.modules.rag.ports import (
    GeneratedAnswerChunk,
    ModelUsage,
    TokenMeasurement,
)


class DashScopeAsyncChatModel:
    """直接调用一次SDK异步流；失败不重试，取消时关闭正在读取的连接。"""

    def __init__(self, settings: Settings | None = None) -> None:
        current_settings = settings or get_settings()
        self.model = current_settings.chat_model_name
        self.api_key = current_settings.require_dashscope_api_key()

    async def stream(
        self, messages: list[dict[str, str]]
    ) -> AsyncIterator[GeneratedAnswerChunk]:
        responses = await AioGeneration.call(
            model=self.model,
            api_key=self.api_key,
            messages=messages,
            result_format="message",
            stream=True,
            incremental_output=True,
        )
        usage_seen = False
        async for response in responses:
            if response.status_code != HTTPStatus.OK:
                raise RuntimeError(response.code or "DashScopeStreamError")
            usage = self._parse_usage(response)
            if usage is not None:
                usage_seen = True
            output = response.output or {}
            choices = output.get("choices") or []
            content = ""
            if choices:
                message = choices[0].get("message") or {}
                content = message.get("content") or ""
            if content or usage is not None:
                yield GeneratedAnswerChunk(content=content, usage=usage)
        if not usage_seen:
            yield GeneratedAnswerChunk(content="", usage=ModelUsage.unknown())

    @classmethod
    def _parse_usage(cls, response: object) -> ModelUsage | None:
        raw = getattr(response, "usage", None)
        if raw is None and isinstance(response, Mapping):
            raw = response.get("usage")
        if raw is None:
            return None
        input_tokens = cls._optional_token(
            cls._read(raw, "input_tokens", "prompt_tokens")
        )
        output_tokens = cls._optional_token(
            cls._read(raw, "output_tokens", "completion_tokens")
        )
        total_tokens = cls._optional_token(cls._read(raw, "total_tokens"))
        measurement = (
            TokenMeasurement.ACTUAL
            if input_tokens is not None and output_tokens is not None
            else TokenMeasurement.UNKNOWN
        )
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            measurement=measurement,
        )

    @staticmethod
    def _read(raw: object, *names: str) -> object:
        for name in names:
            if isinstance(raw, Mapping) and name in raw:
                return raw[name]
            value = getattr(raw, name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _optional_token(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
