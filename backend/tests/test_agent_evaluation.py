"""任务11.8：固定Agent评估集与普通RAG隔离基线。"""

from pathlib import Path

from app.evaluation.agent_evaluation import (
    evaluate_agent_planner,
    load_agent_cases,
)
from app.modules.agent.planner import (
    FinalDecision,
    InspectionDecision,
    PlanDecision,
    ToolDecision,
)

CASES = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "agent_v1_cases.json"
)


class DeterministicEvaluationPlanner:
    def classify_and_plan(self, state):
        forbidden = any(
            word in state["task"]
            for word in ("系统命令", "诊断疾病", "处方")
        )
        return PlanDecision(
            plan=["拒绝越权任务"] if forbidden else ["选择只读资料工具"],
            allowed=not forbidden,
            refusal_message="该任务不在资料整理范围内。" if forbidden else None,
        )

    def select_tool(self, state):
        task = state["task"]
        if "比较" in task:
            name = "compare_documents"
        elif "摘要" in task:
            name = "summarize_document"
        elif "报告" in task:
            name = "generate_learning_report"
        else:
            name = "search_knowledge"
        return ToolDecision(tool_name=name, arguments={})

    def inspect_result(self, state):
        return InspectionDecision(action="finalize", final_output="完成")

    def finalize(self, state):
        return FinalDecision(output="完成")


def test_fixed_agent_evaluation_cases_all_pass_with_reference_planner() -> None:
    cases = load_agent_cases(CASES)
    results = evaluate_agent_planner(DeterministicEvaluationPlanner(), cases)

    assert len(results) == 6
    assert all(item.passed for item in results)
    assert sum(not item.actual_allowed for item in results) == 2


def test_evaluation_dataset_has_all_first_version_tools_and_safety_cases() -> None:
    cases = load_agent_cases(CASES)
    assert {item.expected_tool for item in cases if item.expected_allowed} == {
        "search_knowledge",
        "summarize_document",
        "compare_documents",
        "generate_learning_report",
    }
    assert {item.case_id for item in cases if not item.expected_allowed} == {
        "reject_system_command",
        "reject_medical_diagnosis",
    }


def test_empty_model_plan_can_be_normalized_without_changing_permission_decision() -> None:
    decision = PlanDecision(plan=[], allowed=False, refusal_message="拒绝")
    normalized = decision.plan or [
        "选择只读知识工具" if decision.allowed else "拒绝越权任务"
    ]
    assert normalized == ["拒绝越权任务"]
    assert decision.allowed is False
