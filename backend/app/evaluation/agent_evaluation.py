"""Agent固定工具选择与越权拒绝评估。"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.modules.agent.planner import AgentPlanner
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.state import create_initial_state


@dataclass(frozen=True, slots=True)
class AgentEvaluationCase:
    case_id: str
    task: str
    expected_allowed: bool
    expected_tool: str | None


@dataclass(frozen=True, slots=True)
class AgentEvaluationResult:
    case_id: str
    passed: bool
    actual_allowed: bool
    actual_tool: str | None
    used_tokens: int
    estimated_cost_cny: float


def load_agent_cases(path: Path) -> list[AgentEvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != "agent_tool_selection_v1":
        raise ValueError("不支持的Agent评估集版本")
    cases = [AgentEvaluationCase(**item) for item in payload.get("cases", [])]
    if not cases or len({item.case_id for item in cases}) != len(cases):
        raise ValueError("Agent评估集不能为空且case_id必须唯一")
    return cases


def evaluate_agent_planner(
    planner: AgentPlanner,
    cases: list[AgentEvaluationCase],
) -> list[AgentEvaluationResult]:
    results = []
    for case in cases:
        state = create_initial_state(
            run_id=f"evaluation-{case.case_id}",
            user_id="evaluation-user",
            task=case.task,
            policy=AgentPolicy(enabled=True),
        )
        plan = planner.classify_and_plan(state)
        actual_tool = None
        used_tokens = plan.usage.tokens
        estimated_cost = plan.usage.estimated_cost_cny
        if plan.allowed:
            state["plan"] = plan.plan
            tool = planner.select_tool(state)
            actual_tool = tool.tool_name
            used_tokens += tool.usage.tokens
            estimated_cost += tool.usage.estimated_cost_cny
        results.append(
            AgentEvaluationResult(
                case_id=case.case_id,
                passed=(
                    plan.allowed == case.expected_allowed
                    and actual_tool == case.expected_tool
                ),
                actual_allowed=plan.allowed,
                actual_tool=actual_tool,
                used_tokens=used_tokens,
                estimated_cost_cny=estimated_cost,
            )
        )
    return results
