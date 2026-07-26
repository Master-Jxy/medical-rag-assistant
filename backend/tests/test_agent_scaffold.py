"""任务11.1：默认关闭、仅Mock的Agent骨架。"""

from pydantic import Field, ValidationError
import pytest

from app.core.config import Settings
from app.modules.agent.contracts import (
    AgentToolArguments,
    AgentToolContext,
    AgentToolResult,
)
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import (
    DuplicateToolError,
    ToolNotRegisteredError,
    ToolRegistry,
)
from app.modules.agent.state import (
    AgentNode,
    AgentRunStatus,
    create_initial_state,
)


class MockSearchArguments(AgentToolArguments):
    query: str = Field(min_length=1, max_length=200)


class MockSearchTool:
    name = "mock_search"
    description = "只返回固定摘要的测试工具"
    arguments_model = MockSearchArguments

    def __init__(self) -> None:
        self.calls = []

    def invoke(self, context, arguments):
        self.calls.append((context, arguments))
        return AgentToolResult(summary=f"检索：{arguments.query}", source_ids=["doc-1"])


def test_agent_policy_is_disabled_and_hard_limited_by_default() -> None:
    settings = Settings(_env_file=None)
    policy = AgentPolicy.from_settings(settings)

    assert policy.enabled is False
    assert policy.max_steps == 5
    assert policy.max_tokens == 12_000
    with pytest.raises(ValidationError):
        Settings(_env_file=None, agent_max_steps=6)


def test_initial_state_contains_only_explicit_bounded_business_fields() -> None:
    state = create_initial_state(
        run_id="run-1",
        user_id="user-1",
        task="  比较两份资料  ",
        policy=AgentPolicy(),
    )

    assert state["task"] == "比较两份资料"
    assert state["status"] is AgentRunStatus.PENDING
    assert state["current_node"] is AgentNode.CLASSIFY_AND_PLAN
    assert state["step_count"] == 0
    assert state["max_steps"] == 5
    assert "reasoning" not in state
    assert "chain_of_thought" not in state


def test_registry_only_invokes_registered_tool_after_pydantic_validation() -> None:
    tool = MockSearchTool()
    registry = ToolRegistry([tool])
    context = AgentToolContext(run_id="run-1", user_id="user-1")

    result = registry.invoke("mock_search", context, {"query": "患者安全"})

    assert registry.names() == ("mock_search",)
    assert result.summary == "检索：患者安全"
    assert result.source_ids == ["doc-1"]
    assert tool.calls[0][0] == context
    with pytest.raises(ValidationError):
        registry.invoke("mock_search", context, {"query": "", "extra": "blocked"})
    with pytest.raises(ToolNotRegisteredError):
        registry.invoke("shell", context, {})
    with pytest.raises(DuplicateToolError):
        registry.register(tool)
