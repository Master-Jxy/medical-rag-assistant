"""受步骤、时间、Token和费用约束的显式LangGraph流程。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from time import monotonic
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.modules.agent.contracts import AgentToolContext
from app.modules.agent.planner import AgentPlanner, PlannerUsage
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.state import (
    AgentGraphState,
    AgentNode,
    AgentRunStatus,
    AgentStopReason,
)

Route = Literal["select_tool", "execute_tool", "inspect_result", "finalize", "fail", "stop"]


class AgentToolTimeoutError(TimeoutError):
    pass


def _with_usage(
    state: AgentGraphState,
    usage: PlannerUsage,
) -> dict[str, object]:
    return {
        "used_tokens": state["used_tokens"] + usage.tokens,
        "estimated_cost_cny": (
            state["estimated_cost_cny"] + usage.estimated_cost_cny
        ),
    }


class BoundedAgentGraph:
    def __init__(
        self,
        *,
        planner: AgentPlanner,
        registry: ToolRegistry,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.planner = planner
        self.registry = registry
        self.stop_requested = stop_requested or (lambda: False)
        self._started_at = 0.0
        self.graph = self._build_graph()

    def invoke(self, state: AgentGraphState) -> AgentGraphState:
        self._started_at = monotonic()
        result = self.graph.invoke(state, {"recursion_limit": 40})
        return AgentGraphState(**result)

    def stream_values(self, state: AgentGraphState):
        """逐节点返回完整显式状态，供独立SSE和持久化层观察。"""
        self._started_at = monotonic()
        for value in self.graph.stream(
            state,
            {"recursion_limit": 40},
            stream_mode="values",
        ):
            yield AgentGraphState(**value)

    def _build_graph(self):
        builder = StateGraph(AgentGraphState)
        builder.add_node("classify_and_plan", self._classify_and_plan)
        builder.add_node("select_tool", self._select_tool)
        builder.add_node("execute_tool", self._execute_tool)
        builder.add_node("inspect_result", self._inspect_result)
        builder.add_node("finalize", self._finalize)
        builder.add_node("fail", self._fail)
        builder.add_node("stop", self._stop)
        builder.add_edge(START, "classify_and_plan")
        builder.add_conditional_edges(
            "classify_and_plan",
            self._route_after_plan,
            {"select_tool": "select_tool", "finalize": "finalize", "stop": "stop"},
        )
        builder.add_conditional_edges(
            "select_tool",
            self._route_after_selection,
            {"execute_tool": "execute_tool", "stop": "stop"},
        )
        builder.add_edge("execute_tool", "inspect_result")
        builder.add_conditional_edges(
            "inspect_result",
            self._route_after_inspection,
            {
                "select_tool": "select_tool",
                "finalize": "finalize",
                "fail": "fail",
                "stop": "stop",
            },
        )
        builder.add_edge("finalize", END)
        builder.add_edge("fail", END)
        builder.add_edge("stop", END)
        return builder.compile()

    def _classify_and_plan(self, state: AgentGraphState) -> dict[str, object]:
        decision = self.planner.classify_and_plan(state)
        route = "refuse" if not decision.allowed else decision.route
        should_use_tool = route == "tool_required"
        visible_output = decision.response_message
        if route == "refuse":
            visible_output = (
                decision.refusal_message
                or visible_output
                or "该任务超出资料整理Agent的安全能力范围。"
            )
        return {
            "status": AgentRunStatus.RUNNING,
            "current_node": AgentNode.CLASSIFY_AND_PLAN,
            "plan": decision.plan,
            "next_action": "select_tool" if should_use_tool else "finalize",
            "final_output": None if should_use_tool else visible_output,
            **_with_usage(state, decision.usage),
        }

    def _select_tool(self, state: AgentGraphState) -> dict[str, object]:
        decision = self.planner.select_tool(state)
        return {
            "current_node": AgentNode.SELECT_TOOL,
            "selected_tool": decision.tool_name,
            "tool_arguments": decision.arguments,
            **_with_usage(state, decision.usage),
        }

    def _execute_tool(self, state: AgentGraphState) -> dict[str, object]:
        tool_name = state.get("selected_tool")
        if not tool_name:
            return {
                "current_node": AgentNode.EXECUTE_TOOL,
                "step_count": state["step_count"] + 1,
                "last_tool_result": None,
                "error_type": "TOOL_NOT_SELECTED",
            }
        context = AgentToolContext(
            run_id=state["run_id"],
            user_id=state["user_id"],
            task_context=state["task"],
        )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-tool")
        future = executor.submit(
            self.registry.invoke,
            tool_name,
            context,
            state.get("tool_arguments", {}),
        )
        remaining = max(
            0.001,
            state["run_timeout_seconds"] - (monotonic() - self._started_at),
        )
        timeout = min(state["tool_timeout_seconds"], remaining)
        try:
            result = future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            return {
                "current_node": AgentNode.EXECUTE_TOOL,
                "step_count": state["step_count"] + 1,
                "last_tool_result": None,
                "error_type": "TOOL_TIMEOUT",
            }
        except Exception:
            return {
                "current_node": AgentNode.EXECUTE_TOOL,
                "step_count": state["step_count"] + 1,
                "last_tool_result": None,
                "error_type": "TOOL_EXECUTION_FAILED",
            }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {
            "current_node": AgentNode.EXECUTE_TOOL,
            "step_count": state["step_count"] + 1,
            "last_tool_result": result.model_dump(mode="json"),
            "tool_result_summaries": [
                *state["tool_result_summaries"],
                result.summary,
            ],
            "used_tokens": state["used_tokens"] + result.used_tokens,
            "estimated_cost_cny": (
                state["estimated_cost_cny"] + result.estimated_cost_cny
            ),
            "error_type": None,
        }

    def _inspect_result(self, state: AgentGraphState) -> dict[str, object]:
        if state.get("error_type"):
            return {
                "current_node": AgentNode.INSPECT_RESULT,
                "next_action": "fail",
            }
        decision = self.planner.inspect_result(state)
        return {
            "current_node": AgentNode.INSPECT_RESULT,
            "next_action": (
                "finalize"
                if decision.action == "clarification"
                else decision.action
            ),
            "final_output": decision.final_output,
            "error_type": decision.error_type,
            **_with_usage(state, decision.usage),
        }

    def _finalize(self, state: AgentGraphState) -> dict[str, object]:
        if state.get("final_output"):
            return {
                "current_node": AgentNode.FINALIZE,
                "status": AgentRunStatus.COMPLETED,
            }
        decision = self.planner.finalize(state)
        usage = _with_usage(state, decision.usage)
        projected = {**state, **usage}
        stop_reason = self._budget_stop_reason(projected)
        if stop_reason:
            return {
                "current_node": AgentNode.FINALIZE,
                "status": AgentRunStatus.STOPPED,
                "stop_reason": stop_reason,
                "final_output": "Agent已达到运行预算并安全停止。",
                **usage,
            }
        return {
            "current_node": AgentNode.FINALIZE,
            "status": AgentRunStatus.COMPLETED,
            "final_output": decision.output,
            **usage,
        }

    @staticmethod
    def _fail(state: AgentGraphState) -> dict[str, object]:
        return {
            "status": AgentRunStatus.FAILED,
            "error_type": state.get("error_type") or "AGENT_EXECUTION_FAILED",
            "final_output": "Agent未能完成任务，请稍后重试。",
        }

    def _stop(self, state: AgentGraphState) -> dict[str, object]:
        reason = self._stop_reason(state) or AgentStopReason.USER_REQUESTED
        return {
            "status": AgentRunStatus.STOPPED,
            "stop_reason": reason,
            "final_output": "Agent已按安全边界停止运行。",
        }

    def _route_after_plan(
        self, state: AgentGraphState
    ) -> Literal["select_tool", "finalize", "stop"]:
        if self._stop_reason(state):
            return "stop"
        return "finalize" if state.get("next_action") == "finalize" else "select_tool"

    def _route_after_selection(
        self, state: AgentGraphState
    ) -> Literal["execute_tool", "stop"]:
        return "stop" if self._stop_reason(state) else "execute_tool"

    def _route_after_inspection(self, state: AgentGraphState) -> Route:
        if state.get("next_action") == "fail":
            return "fail"
        if self._stop_reason(state):
            return "stop"
        if state.get("next_action") == "finalize":
            return "finalize"
        return "select_tool"

    def _stop_reason(self, state: AgentGraphState) -> AgentStopReason | None:
        if self.stop_requested():
            return AgentStopReason.USER_REQUESTED
        if monotonic() - self._started_at >= state["run_timeout_seconds"]:
            return AgentStopReason.TIMEOUT
        return self._budget_stop_reason(state)

    @staticmethod
    def _budget_stop_reason(state: AgentGraphState) -> AgentStopReason | None:
        if state["used_tokens"] > state["max_tokens"]:
            return AgentStopReason.TOKEN_BUDGET
        if state["estimated_cost_cny"] > state["max_estimated_cost_cny"]:
            return AgentStopReason.COST_BUDGET
        if (
            state["step_count"] >= state["max_steps"]
            and state.get("next_action") == "continue"
        ):
            return AgentStopReason.STEP_LIMIT
        return None
