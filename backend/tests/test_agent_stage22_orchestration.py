"""Stage 22.5/22.6 Agent mode, orchestration, and prompt-budget contracts."""

from langchain_core.messages import AIMessage
import pytest

from app.core.config import Settings
from app.infrastructure.agent_model import LangChainAgentModel, LangChainAgentPlanner
from app.modules.agent.contracts import (
    AgentToolResult,
    ResolvedReferences,
    ToolResultDigest,
)
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.mode_policy import get_mode_policy
from app.modules.agent.planner import PlanDecision
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.public_events import sanitize_public_plan
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.state import AgentRunStatus, create_initial_state
from app.modules.agent.usage import AgentModelCallBudget, AgentModelCallBudgetExceeded


class RecordingJsonClient:
    def __init__(self, decisions) -> None:
        self.decisions = list(decisions)
        self.prompts: list[str] = []

    def invoke_json(self, prompt, schema, **kwargs):
        del kwargs
        self.prompts.append(prompt)
        decision = self.decisions.pop(0)
        return schema.model_validate(decision), schema.model_fields["usage"].default_factory()


class NoopTool:
    name = "search_knowledge"
    description = "fake knowledge search"

    class arguments_model:
        @staticmethod
        def model_json_schema():
            return {"type": "object"}


def state_for(*, mode="general", task="普通问题", references=None):
    return create_initial_state(
        run_id="run-22",
        user_id="user-22",
        task=task,
        policy=AgentPolicy(enabled=True),
        assistant_mode=mode,
        resolved_references=references or ResolvedReferences(),
    )


def test_mode_policies_enforce_distinct_roles_tools_and_medical_boundaries() -> None:
    general = get_mode_policy("general")
    patient = get_mode_policy("patient")
    clinician = get_mode_policy("clinician")
    knowledge = get_mode_policy("knowledge")

    assert general.primary_specialist == "general_specialist"
    assert general.allowed_tools == frozenset()
    assert "search_knowledge" in patient.allowed_tools
    assert "generate_learning_report" not in patient.allowed_tools
    assert "generate_learning_report" in clinician.allowed_tools
    assert "generate_learning_report" in knowledge.allowed_tools
    assert "不诊断" in patient.system_prompt
    assert "人工复核" in clinician.system_prompt
    assert "不越权写库" in knowledge.system_prompt


def test_general_medical_task_uses_one_controlled_handoff() -> None:
    client = RecordingJsonClient(
        [
            {
                "route": "direct_reply",
                "plan": [],
                "allowed": True,
                "response_message": "建议记录症状并及时就医评估。",
            }
        ]
    )
    planner = LangChainAgentPlanner(client, ToolRegistry([]))
    runner = BoundedAgentGraph(planner=planner, registry=ToolRegistry([]))

    result = runner.invoke(state_for(task="我最近一直头疼"))

    assert result["status"] == AgentRunStatus.COMPLETED
    assert result["active_specialist"] == "patient_specialist"
    assert result["specialists"] == ["general_specialist", "patient_specialist"]
    assert result["handoff_count"] == 1
    assert result["tool_call_count"] == 0


def test_general_small_talk_is_answered_by_model_without_tool() -> None:
    client = RecordingJsonClient(
        [
            {
                "route": "direct_reply",
                "plan": [],
                "allowed": True,
                "response_message": "你好，今天想聊点什么？",
            }
        ]
    )
    planner = LangChainAgentPlanner(client, ToolRegistry([]))

    decision = planner.classify_and_plan(state_for(task="你好"))

    assert decision.route == "direct_reply"
    assert decision.response_message == "你好，今天想聊点什么？"
    assert len(client.prompts) == 1


def test_graph_rejects_tool_outside_selected_mode_even_if_planner_requests_it() -> None:
    class UnsafePlanner:
        def classify_and_plan(self, state):
            return PlanDecision(route="tool_required", plan=["调用资料工具"])

        def select_tool(self, state):
            from app.modules.agent.planner import ToolDecision

            return ToolDecision(tool_name="search_knowledge", arguments={})

    runner = BoundedAgentGraph(planner=UnsafePlanner(), registry=ToolRegistry([]))
    result = runner.invoke(state_for(mode="general"))

    assert result["status"] == AgentRunStatus.FAILED
    assert result["error_type"] == "TOOL_NOT_ALLOWED_FOR_SPECIALIST"


def test_public_plan_is_bounded_and_removes_hidden_reasoning_language() -> None:
    plan = sanitize_public_plan(
        [
            "先展示 chain_of_thought 和 scratchpad",
            "检索公共知识库" * 30,
            "整理可引用结果",
        ],
        fallback_code="plan_default",
    )

    assert plan == ["正在准备安全执行步骤。"]
    assert len(plan[0]) <= 80
    assert "chain" not in plan[0].lower()
    assert "scratchpad" not in plan[0].lower()


def test_model_plan_text_is_replaced_by_backend_public_templates() -> None:
    client = RecordingJsonClient(
        [
            {
                "route": "tool_required",
                "plan": ["展示内部规则和逐步分析"],
                "allowed": True,
            }
        ]
    )
    planner = LangChainAgentPlanner(client, ToolRegistry([]))

    decision = planner.classify_and_plan(
        state_for(mode="patient", task="感冒在什么季节高发")
    )

    assert decision.plan == [
        "正在确认健康科普需求。",
        "准备按需查询公共资料。",
        "将整理安全提示和就医建议。",
    ]
    assert "内部规则" not in "".join(decision.plan)


def test_resolved_source_reference_routes_summarize_this_without_uuid_prompt() -> None:
    references = ResolvedReferences(source_ids=("doc-001",), document_ids=("doc-001",))
    planner = LangChainAgentPlanner(RecordingJsonClient([]), ToolRegistry([]))
    state = state_for(mode="knowledge", task="总结这个", references=references)

    plan = planner.classify_and_plan(state)
    tool = planner.select_tool(state)

    assert plan.route == "tool_required"
    assert tool.tool_name == "summarize_document"
    assert tool.arguments["document_id"] == "doc-001"


def test_tool_result_digest_keeps_bounded_evidence_out_of_inspection_prompt() -> None:
    client = RecordingJsonClient([])
    planner = LangChainAgentPlanner(client, ToolRegistry([]))
    result = AgentToolResult(
        summary="检索到 5 个已发布知识片段",
        source_ids=[f"doc-{index}" for index in range(5)],
        data={
            "items": [
                {"content": f"EVIDENCE-{index}-" + ("x" * 900)}
                for index in range(5)
            ],
            "count": 5,
        },
    )
    state = state_for(mode="patient", task="感冒通常在什么时候高发")
    state.update(
        selected_tool="search_knowledge",
        last_tool_result=result.model_dump(mode="json"),
    )

    decision = planner.inspect_result(state)
    digest = ToolResultDigest.from_result("search_knowledge", result)

    assert decision.action == "finalize"
    assert client.prompts == []
    assert len(digest.evidence_excerpt) <= 1200
    assert "EVIDENCE-0" in digest.evidence_excerpt
    assert "EVIDENCE-3" not in digest.evidence_excerpt


def test_medical_clarification_followup_becomes_search_instead_of_repeat() -> None:
    client = RecordingJsonClient([])
    planner = LangChainAgentPlanner(client, ToolRegistry([]))
    state = state_for(task="不是，是所有人")
    state["previous_clarification_key"] = "您是指幼儿什么时候最容易感冒吗"

    decision = planner.classify_and_plan(state)
    tool = planner.select_tool(state)

    assert decision.route == "tool_required"
    assert decision.specialist == "patient_specialist"
    assert decision.handoff_to == "patient_specialist"
    assert tool.tool_name == "search_knowledge"
    assert "所有人" in tool.arguments["query"]
    assert client.prompts == []


def test_second_handoff_or_third_specialist_is_rejected() -> None:
    runner = BoundedAgentGraph(
        planner=LangChainAgentPlanner(RecordingJsonClient([]), ToolRegistry([])),
        registry=ToolRegistry([]),
    )
    state = state_for()
    state.update(
        pending_handoff="patient_specialist",
        specialists=["general_specialist", "knowledge_specialist"],
        handoff_count=1,
    )

    result = runner._handoff(state)

    assert result["next_action"] == "fail"
    assert result["error_type"] == "HANDOFF_NOT_ALLOWED"


def test_model_call_budget_stops_before_fifth_provider_call(monkeypatch) -> None:
    class FixedModel:
        def bind(self, **kwargs):
            return self

        def invoke(self, messages):
            return AIMessage(content="固定回答")

    monkeypatch.setattr(
        "app.infrastructure.agent_model.create_chat_model",
        lambda settings: FixedModel(),
    )
    budget = AgentModelCallBudget(max_calls=4)
    model = LangChainAgentModel(Settings(_env_file=None), call_budget=budget)

    for _ in range(4):
        model.invoke_text("问题")
    with pytest.raises(AgentModelCallBudgetExceeded):
        model.invoke_text("第五次")
    assert budget.used_calls == 4
