"""任务11.4：LangGraph显式流程和硬预算。"""

from time import sleep

import pytest

from app.modules.agent.contracts import (
    AgentToolArguments,
    AgentToolContext,
    AgentToolResult,
)
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.planner import (
    FinalDecision,
    InspectionDecision,
    PlanDecision,
    PlannerUsage,
    ToolDecision,
)
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.state import (
    AgentRunStatus,
    AgentStopReason,
    create_initial_state,
)


class EmptyArguments(AgentToolArguments):
    pass


class StubTool:
    name = "search_knowledge"
    description = "返回固定的用户可见结果"
    arguments_model = EmptyArguments

    def __init__(self, delay: float = 0) -> None:
        self.delay = delay
        self.contexts: list[AgentToolContext] = []

    def invoke(
        self,
        context: AgentToolContext,
        arguments: AgentToolArguments,
    ) -> AgentToolResult:
        self.contexts.append(context)
        del arguments
        if self.delay:
            sleep(self.delay)
        return AgentToolResult(summary="已找到资料", source_ids=["doc-1"])


class StubPlanner:
    def __init__(
        self,
        *,
        action: str = "finalize",
        usage: PlannerUsage | None = None,
    ) -> None:
        self.action = action
        self.usage = usage or PlannerUsage()

    def classify_and_plan(self, state):
        return PlanDecision(plan=["检索资料", "形成结论"], usage=self.usage)

    def select_tool(self, state):
        return ToolDecision(tool_name="search_knowledge", arguments={})

    def inspect_result(self, state):
        return InspectionDecision(
            action=self.action,
            final_output="基于资料完成整理。" if self.action == "finalize" else None,
        )

    def finalize(self, state):
        return FinalDecision(output="基于资料完成整理。")


def initial_state(policy: AgentPolicy):
    return create_initial_state(
        run_id="run-1",
        user_id="user-1",
        task="整理患者安全资料",
        policy=policy,
        assistant_mode="knowledge",
    )


def test_graph_runs_explicit_nodes_and_finishes() -> None:
    tool = StubTool()
    runner = BoundedAgentGraph(
        planner=StubPlanner(),
        registry=ToolRegistry([tool]),
    )
    result = runner.invoke(initial_state(AgentPolicy(enabled=True)))

    assert result["status"] == AgentRunStatus.COMPLETED
    assert result["step_count"] == 1
    assert result["tool_result_summaries"] == ["已找到资料"]
    assert result["final_output"] == "基于资料完成整理。"
    assert tool.contexts[0].task_context == "整理患者安全资料"
    assert {"classify_and_plan", "select_tool", "execute_tool", "inspect_result"} <= set(
        runner.graph.get_graph().nodes
    )


def test_graph_stops_at_step_limit_without_unbounded_loop() -> None:
    runner = BoundedAgentGraph(
        planner=StubPlanner(action="continue"),
        registry=ToolRegistry([StubTool()]),
    )
    result = runner.invoke(initial_state(AgentPolicy(enabled=True, max_steps=2)))

    assert result["status"] == AgentRunStatus.STOPPED
    assert result["stop_reason"] == AgentStopReason.STEP_LIMIT
    assert result["step_count"] == 2


@pytest.mark.parametrize(
    ("usage", "reason"),
    [
        (PlannerUsage(tokens=11), AgentStopReason.TOKEN_BUDGET),
        (PlannerUsage(estimated_cost_cny=0.02), AgentStopReason.COST_BUDGET),
    ],
)
def test_graph_stops_before_tools_when_planning_exceeds_budget(usage, reason) -> None:
    policy = AgentPolicy(
        enabled=True,
        max_tokens=10,
        max_estimated_cost_cny=0.01,
    )
    runner = BoundedAgentGraph(
        planner=StubPlanner(usage=usage),
        registry=ToolRegistry([StubTool()]),
    )
    result = runner.invoke(initial_state(policy))

    assert result["status"] == AgentRunStatus.STOPPED
    assert result["stop_reason"] == reason
    assert result["step_count"] == 0


def test_graph_converts_tool_timeout_to_safe_failure() -> None:
    runner = BoundedAgentGraph(
        planner=StubPlanner(),
        registry=ToolRegistry([StubTool(delay=0.05)]),
    )
    result = runner.invoke(
        initial_state(
            AgentPolicy(
                enabled=True,
                tool_timeout_seconds=0.01,
                run_timeout_seconds=1,
            )
        )
    )

    assert result["status"] == AgentRunStatus.FAILED
    assert result["error_type"] == "TOOL_TIMEOUT"
    assert "Traceback" not in result["final_output"]


def test_graph_honors_user_stop_before_any_tool() -> None:
    runner = BoundedAgentGraph(
        planner=StubPlanner(),
        registry=ToolRegistry([StubTool()]),
        stop_requested=lambda: True,
    )
    result = runner.invoke(initial_state(AgentPolicy(enabled=True)))

    assert result["status"] == AgentRunStatus.STOPPED
    assert result["stop_reason"] == AgentStopReason.USER_REQUESTED
    assert result["step_count"] == 0


def test_graph_refuses_unsupported_task_without_selecting_tool() -> None:
    planner = StubPlanner()
    planner.classify_and_plan = lambda state: PlanDecision(
        plan=["拒绝越权任务"],
        allowed=False,
        refusal_message="不支持执行系统命令。",
    )
    runner = BoundedAgentGraph(
        planner=planner,
        registry=ToolRegistry([StubTool()]),
    )
    result = runner.invoke(initial_state(AgentPolicy(enabled=True)))

    assert result["status"] == AgentRunStatus.COMPLETED
    assert result["step_count"] == 0
    assert result["final_output"] == "不支持执行系统命令。"


def test_graph_direct_reply_completes_without_tool_step() -> None:
    planner = StubPlanner()
    planner.classify_and_plan = lambda state: PlanDecision(
        route="direct_reply",
        response_message="你好，我是资料整理Agent。",
    )
    runner = BoundedAgentGraph(
        planner=planner,
        registry=ToolRegistry([StubTool()]),
    )
    result = runner.invoke(initial_state(AgentPolicy(enabled=True)))

    assert result["status"] == AgentRunStatus.COMPLETED
    assert result["step_count"] == 0
    assert result["final_output"] == "你好，我是资料整理Agent。"
