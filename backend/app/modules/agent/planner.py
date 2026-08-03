"""Agent规划器契约；只交换显式业务决策，不交换隐藏推理。"""

from collections.abc import Iterator
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.agent.state import AgentGraphState
from app.modules.agent.generation import GeneratedAgentTextChunk
from app.modules.agent.mode_policy import ALL_SPECIALISTS
from app.modules.agent.public_events import sanitize_public_plan


class PlannerUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tokens: int = Field(default=0, ge=0)
    estimated_cost_cny: float = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0, le=1)


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: list[str] = Field(default_factory=list, max_length=5)
    route: Literal[
        "direct_reply",
        "clarification",
        "tool_required",
        "refuse",
    ] = "tool_required"
    allowed: bool = True
    refusal_message: str | None = Field(default=None, max_length=500)
    response_message: str | None = Field(default=None, max_length=2000)
    specialist: str | None = Field(default=None, max_length=40)
    handoff_to: str | None = Field(default=None, max_length=40)
    clarification_key: str | None = Field(default=None, max_length=160)
    usage: PlannerUsage = Field(default_factory=PlannerUsage)

    @field_validator("plan", mode="before")
    @classmethod
    def normalize_empty_plan(cls, value):
        """非工具路由常被模型表示为null，统一为无公开执行计划。"""
        return [] if value is None else value

    @field_validator("plan")
    @classmethod
    def sanitize_plan(cls, value: list[str]) -> list[str]:
        if not value:
            return []
        return sanitize_public_plan(value)

    @field_validator("specialist", "handoff_to")
    @classmethod
    def validate_specialist(cls, value: str | None) -> str | None:
        if value is not None and value not in ALL_SPECIALISTS:
            raise ValueError("specialist不在受控注册表")
        return value


class ToolDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, object]
    usage: PlannerUsage = Field(default_factory=PlannerUsage)


class InspectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue", "finalize", "clarification", "fail"]
    final_output: str | None = Field(default=None, max_length=20_000)
    error_type: str | None = Field(default=None, max_length=100)
    usage: PlannerUsage = Field(default_factory=PlannerUsage)


class FinalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: str = Field(min_length=1, max_length=20_000)
    usage: PlannerUsage = Field(default_factory=PlannerUsage)


class AgentPlanner(Protocol):
    """实现可由LangChain模型或确定性Mock提供。"""

    def classify_and_plan(self, state: AgentGraphState) -> PlanDecision: ...

    def select_tool(self, state: AgentGraphState) -> ToolDecision: ...

    def inspect_result(self, state: AgentGraphState) -> InspectionDecision: ...

    def finalize(self, state: AgentGraphState) -> FinalDecision: ...

    def stream_finalize(
        self,
        state: AgentGraphState,
    ) -> Iterator[GeneratedAgentTextChunk]: ...
