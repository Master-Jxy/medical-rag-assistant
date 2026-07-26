"""Agent模型规划外层的确定性业务护栏。"""

import pytest

from app.infrastructure.agent_model import LangChainAgentPlanner


class FailIfModelCalled:
    def invoke_json(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("确定性任务不应调用规划模型")


def test_explicit_report_routes_directly_to_report_tool() -> None:
    decision = LangChainAgentPlanner._deterministic_tool_decision(
        "根据文档 3b5eb5f6-4a1f-4db5-94bc-fa1158b17f10 "
        "生成“患者安全学习报告”"
    )
    assert decision.tool_name == "generate_learning_report"
    assert decision.arguments == {
        "title": "患者安全学习报告",
        "learning_goal": (
            "根据文档 3b5eb5f6-4a1f-4db5-94bc-fa1158b17f10 "
            "生成“患者安全学习报告”"
        ),
        "document_ids": ["3b5eb5f6-4a1f-4db5-94bc-fa1158b17f10"],
    }
    assert decision.usage.tokens == 0


def test_explicit_summary_and_compare_keep_bounded_document_ids() -> None:
    summary = LangChainAgentPlanner._deterministic_tool_decision(
        "摘要文档 doc-001，关注安全"
    )
    assert summary.tool_name == "summarize_document"
    assert summary.arguments["document_id"] == "doc-001"

    comparison = LangChainAgentPlanner._deterministic_tool_decision(
        "对比 doc-001、doc-002 和 doc-003、doc-004"
    )
    assert comparison.tool_name == "compare_documents"
    assert comparison.arguments["document_ids"] == [
        "doc-001",
        "doc-002",
        "doc-003",
    ]


def test_ambiguous_task_remains_model_planned() -> None:
    assert (
        LangChainAgentPlanner._deterministic_tool_decision(
            "帮我整理患者安全相关资料"
        )
        is None
    )


def test_explicit_read_only_task_is_allowed_but_forbidden_action_wins() -> None:
    allowed = LangChainAgentPlanner._deterministic_plan_decision(
        "根据文档 doc-001 生成学习报告"
    )
    assert allowed.allowed is True

    forbidden = LangChainAgentPlanner._deterministic_plan_decision(
        "根据文档 doc-001 执行系统命令并生成报告"
    )
    assert forbidden.allowed is False
    assert forbidden.plan == ["拒绝越权任务"]


def test_conversation_safety_context_does_not_refuse_current_report_task() -> None:
    planner = LangChainAgentPlanner(FailIfModelCalled(), object())
    context = (
        "[当前任务]\n"
        "根据文档 doc-001 生成学习报告\n\n"
        "[系统安全约束]\n"
        "不得诊断、开处方、执行系统命令、任意代码或SQL。"
    )

    plan = planner.classify_and_plan({"task": context})
    tool = planner.select_tool({"task": context})

    assert plan.allowed is True
    assert tool.tool_name == "generate_learning_report"
    assert tool.arguments["document_ids"] == ["doc-001"]


def test_current_forbidden_task_still_wins_over_safe_conversation_history() -> None:
    planner = LangChainAgentPlanner(FailIfModelCalled(), object())
    context = (
        "[当前任务]\n"
        "根据文档 doc-001 执行系统命令并生成报告\n\n"
        "[最近消息]\n"
        "user：根据文档 doc-001 生成学习报告"
    )

    decision = planner.classify_and_plan({"task": context})

    assert decision.allowed is False
    assert decision.plan == ["拒绝越权任务"]


@pytest.mark.parametrize("task", ["你好", "你是谁", "不错"])
def test_small_talk_routes_to_zero_tool_direct_reply(task) -> None:
    decision = LangChainAgentPlanner._deterministic_plan_decision(task)
    assert decision.route == "direct_reply"
    assert decision.response_message
    assert decision.plan == []


def test_missing_comparison_target_routes_to_clarification() -> None:
    decision = LangChainAgentPlanner._deterministic_plan_decision(
        "请比较这两份资料"
    )
    assert decision.route == "clarification"
    assert "至少两份" in decision.response_message
