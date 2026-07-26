"""Agent工具白名单、参数校验和调用入口。"""

import re
from collections.abc import Iterable

from app.modules.agent.contracts import (
    AgentTool,
    AgentToolContext,
    AgentToolResult,
)

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class DuplicateToolError(ValueError):
    pass


class InvalidToolDefinitionError(ValueError):
    pass


class ToolNotRegisteredError(LookupError):
    pass


class ToolRegistry:
    """只有显式注册的工具才能被Agent状态图调用。"""

    def __init__(self, tools: Iterable[AgentTool] = ()) -> None:
        self._tools: dict[str, AgentTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: AgentTool) -> None:
        name = tool.name.strip()
        description = tool.description.strip()
        if not TOOL_NAME_PATTERN.fullmatch(name) or not description:
            raise InvalidToolDefinitionError("工具名称或说明不符合白名单契约")
        if name in self._tools:
            raise DuplicateToolError(f"工具已注册：{name}")
        self._tools[name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def definitions(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.arguments_model.model_json_schema(),
            }
            for tool in sorted(self._tools.values(), key=lambda item: item.name)
        ]

    def invoke(
        self,
        name: str,
        context: AgentToolContext,
        raw_arguments: dict[str, object],
    ) -> AgentToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotRegisteredError(f"工具未注册：{name}")
        arguments = tool.arguments_model.model_validate(raw_arguments)
        return tool.invoke(context, arguments)
