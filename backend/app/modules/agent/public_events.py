"""只公开稳定模板，不公开模型隐藏推理。"""

import re

FORBIDDEN_PUBLIC_PATTERNS = (
    "reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "scratchpad",
    "private_thought",
    "思维过程",
    "隐藏推理",
    "内部推理",
    "系统prompt",
)
PUBLIC_PLAN_FALLBACKS = {
    "plan_default": "正在准备安全执行步骤。",
    "knowledge": "正在准备检索公共知识库。",
    "finalize": "正在组织最终回答。",
}
PUBLIC_PLANS = {
    "general_specialist": (
        "正在确认任务目标。",
        "将按当前上下文组织回答。",
    ),
    "patient_specialist": (
        "正在确认健康科普需求。",
        "准备按需查询公共资料。",
        "将整理安全提示和就医建议。",
    ),
    "clinician_specialist": (
        "正在明确资料与证据需求。",
        "准备检索并比较可引用来源。",
        "将整理结果并提示人工复核。",
    ),
    "knowledge_specialist": (
        "正在确认需要处理的资料范围。",
        "准备调用只读知识工具。",
        "将根据可引用结果组织回答。",
    ),
}

PUBLIC_SUMMARIES = {
    "task_classified": "已完成任务类型判断。",
    "handoff_started": "正在切换到适合当前任务的助手。",
    "handoff_completed": "已切换到适合当前任务的助手。",
    "tool_started": "正在调用受控工具。",
    "tool_completed": "受控工具已完成。",
    "tool_failed": "受控工具未能完成。",
    "result_sufficient": "现有结果足以完成任务，正在组织最终回答。",
    "result_needs_tool": "当前结果不足，正在选择下一项受控工具。",
    "result_failed": "工具结果不可用，任务将安全结束。",
}


def sanitize_public_plan(
    plan: list[str],
    *,
    fallback_code: str = "plan_default",
) -> list[str]:
    safe: list[str] = []
    for raw in plan[:5]:
        value = re.sub(r"\s+", " ", str(raw)).strip()
        lowered = value.lower()
        if not value or any(item in lowered for item in FORBIDDEN_PUBLIC_PATTERNS):
            return [PUBLIC_PLAN_FALLBACKS.get(fallback_code, PUBLIC_PLAN_FALLBACKS["plan_default"])]
        safe.append(value[:80])
    return safe or [PUBLIC_PLAN_FALLBACKS.get(fallback_code, PUBLIC_PLAN_FALLBACKS["plan_default"])]


def public_summary(code: str) -> str:
    return PUBLIC_SUMMARIES.get(code, "Agent正在安全处理任务。")


def public_plan_for_specialist(specialist: str) -> list[str]:
    """公开计划只来自后端模板，模型自由文本不得直接进入页面。"""
    return list(PUBLIC_PLANS.get(specialist, PUBLIC_PLANS["general_specialist"]))


def normalize_clarification_key(text: str | None) -> str | None:
    if not text:
        return None
    normalized = re.sub(r"[\s，。！？、,.!?：:；;]+", "", text).strip().lower()
    for prefix in ("请提供", "请说明", "请确认", "您是指", "你是指"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized[:160] or None
