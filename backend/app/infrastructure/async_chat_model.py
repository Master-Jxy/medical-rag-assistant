"""可取消的 DashScope 异步流式聊天适配器。"""

from collections.abc import AsyncIterator
from http import HTTPStatus

from dashscope.aigc.generation import AioGeneration

from app.core.config import Settings, get_settings


class DashScopeAsyncChatModel:
    """直接使用 SDK 的异步 HTTP 流，取消任务时会关闭正在读取的连接。"""

    def __init__(self, settings: Settings | None = None) -> None:
        current_settings = settings or get_settings()
        self.model = current_settings.chat_model_name
        self.api_key = current_settings.require_dashscope_api_key()

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        responses = await AioGeneration.call(
            model=self.model,
            api_key=self.api_key,
            messages=messages,
            result_format="message",
            stream=True,
            incremental_output=True,
        )
        async for response in responses:
            if response.status_code != HTTPStatus.OK:
                raise RuntimeError(response.code or "DashScopeStreamError")
            output = response.output or {}
            choices = output.get("choices") or []
            if not choices:
                continue
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            if content:
                yield content
