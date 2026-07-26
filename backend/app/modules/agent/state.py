"""LangGraph可使用的显式状态契约；本步不创建或执行状态图。"""

from typing_extensions import NotRequired, TypedDict

from app.core.enums import StrEnum
from app.modules.agent.policy import AgentPolicy


class AgentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentNode(StrEnum):
    CLASSIFY_AND_PLAN = "classify_and_plan"
    SELECT_TOOL = "select_tool"
    EXECUTE_TOOL = "execute_tool"
    INSPECT_RESULT = "inspect_result"
    FINALIZE = "finalize"


class AgentStopReason(StrEnum):
    USER_REQUESTED = "user_requested"
    STEP_LIMIT = "step_limit"
    TIMEOUT = "timeout"
    TOKEN_BUDGET = "token_budget"
    COST_BUDGET = "cost_budget"


class AgentGraphState(TypedDict):
    """只包含可持久化业务状态，不包含Chain-of-Thought。"""

    run_id: str
    user_id: str
    task: str
    status: AgentRunStatus
    current_node: AgentNode
    plan: list[str]
    step_count: int
    max_steps: int
    tool_timeout_seconds: float
    run_timeout_seconds: float
    max_tokens: int
    used_tokens: int
    max_estimated_cost_cny: float
    estimated_cost_cny: float
    selected_tool: NotRequired[str | None]
    tool_arguments: NotRequired[dict[str, object]]
    tool_result_summaries: list[str]
    last_tool_result: NotRequired[dict[str, object] | None]
    next_action: NotRequired[str | None]
    final_output: NotRequired[str | None]
    error_type: NotRequired[str | None]
    stop_reason: NotRequired[AgentStopReason | None]


def create_initial_state(
    *,
    run_id: str,
    user_id: str,
    task: str,
    policy: AgentPolicy,
) -> AgentGraphState:
    normalized_task = task.strip()
    if not run_id.strip() or not user_id.strip():
        raise ValueError("Agent运行ID和用户ID不能为空")
    if not normalized_task or len(normalized_task) > 4000:
        raise ValueError("Agent任务必须为1到4000个非空字符")
    return AgentGraphState(
        run_id=run_id,
        user_id=user_id,
        task=normalized_task,
        status=AgentRunStatus.PENDING,
        current_node=AgentNode.CLASSIFY_AND_PLAN,
        plan=[],
        step_count=0,
        max_steps=policy.max_steps,
        tool_timeout_seconds=policy.tool_timeout_seconds,
        run_timeout_seconds=policy.run_timeout_seconds,
        max_tokens=policy.max_tokens,
        used_tokens=0,
        max_estimated_cost_cny=policy.max_estimated_cost_cny,
        estimated_cost_cny=0.0,
        selected_tool=None,
        tool_arguments={},
        tool_result_summaries=[],
        last_tool_result=None,
        next_action=None,
        final_output=None,
        error_type=None,
        stop_reason=None,
    )
