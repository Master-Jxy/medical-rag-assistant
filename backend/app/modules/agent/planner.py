"""Agent规划器契约；只交换显式业务决策，不交换隐藏推理。"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.modules.agent.state import AgentGraphState


class PlannerUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tokens: int = Field(default=0, ge=0)
    estimated_cost_cny: float = Field(default=0, ge=0)


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: list[str] = Field(default_factory=list, max_length=5)
    allowed: bool = True
    refusal_message: str | None = Field(default=None, max_length=500)
    usage: PlannerUsage = Field(default_factory=PlannerUsage)


class ToolDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, object]
    usage: PlannerUsage = Field(default_factory=PlannerUsage)


class InspectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue", "finalize", "fail"]
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
