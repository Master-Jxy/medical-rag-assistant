"""LangGraph可使用的显式状态契约；本步不创建或执行状态图。"""

from typing_extensions import NotRequired, TypedDict

from app.core.enums import StrEnum
from app.modules.agent.contracts import ResolvedReferences
from app.modules.agent.mode_policy import get_mode_policy, tools_for_specialist
from app.modules.agent.policy import AgentPolicy


class AgentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentNode(StrEnum):
    CLASSIFY_AND_PLAN = "classify_and_plan"
    HANDOFF = "handoff"
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
    assistant_mode: str
    active_specialist: str
    specialists: list[str]
    handoff_count: int
    max_handoffs: int
    max_specialists: int
    pending_handoff: NotRequired[str | None]
    post_handoff_action: NotRequired[str | None]
    allowed_tools: list[str]
    step_count: int
    tool_call_count: int
    max_tool_calls: int
    model_call_count: int
    max_model_calls: int
    inspection_model_calls: int
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
    tool_result_digests: list[dict[str, object]]
    last_tool_result: NotRequired[dict[str, object] | None]
    next_action: NotRequired[str | None]
    final_output: NotRequired[str | None]
    error_type: NotRequired[str | None]
    stop_reason: NotRequired[AgentStopReason | None]
    resolved_references: dict[str, object]
    previous_clarification_key: NotRequired[str | None]
    clarification_key: NotRequired[str | None]
    context_budget: dict[str, int]


def create_initial_state(
    *,
    run_id: str,
    user_id: str,
    task: str,
    policy: AgentPolicy,
    assistant_mode: str = "general",
    resolved_references: ResolvedReferences | None = None,
    previous_clarification_key: str | None = None,
    context_budget: dict[str, int] | None = None,
) -> AgentGraphState:
    normalized_task = task.strip()
    if not run_id.strip() or not user_id.strip():
        raise ValueError("Agent运行ID和用户ID不能为空")
    if not normalized_task or len(normalized_task) > 4000:
        raise ValueError("Agent任务必须为1到4000个非空字符")
    mode_policy = get_mode_policy(assistant_mode)
    primary = mode_policy.primary_specialist
    return AgentGraphState(
        run_id=run_id,
        user_id=user_id,
        task=normalized_task,
        status=AgentRunStatus.PENDING,
        current_node=AgentNode.CLASSIFY_AND_PLAN,
        plan=[],
        assistant_mode=assistant_mode,
        active_specialist=primary,
        specialists=[primary],
        handoff_count=0,
        max_handoffs=policy.max_handoffs,
        max_specialists=policy.max_specialists,
        pending_handoff=None,
        post_handoff_action=None,
        allowed_tools=sorted(tools_for_specialist(primary)),
        step_count=0,
        tool_call_count=0,
        max_tool_calls=policy.max_tool_calls,
        model_call_count=0,
        max_model_calls=policy.max_model_calls,
        inspection_model_calls=0,
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
        tool_result_digests=[],
        last_tool_result=None,
        next_action=None,
        final_output=None,
        error_type=None,
        stop_reason=None,
        resolved_references=(resolved_references or ResolvedReferences()).model_dump(
            mode="json"
        ),
        previous_clarification_key=previous_clarification_key,
        clarification_key=None,
        context_budget=dict(context_budget or {}),
    )
