"""Agent模型规划外层的确定性业务护栏。"""

from app.infrastructure.agent_model import LangChainAgentPlanner


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
