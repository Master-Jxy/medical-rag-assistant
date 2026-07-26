"""Agent REST与SSE公开契约。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=4000)


class AgentStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    node_name: str
    tool_name: str | None
    parameters: dict[str, object]
    result_summary: str | None
    status: str
    duration_ms: int | None
    error_type: str | None
    created_at: datetime
    finished_at: datetime | None


class AgentArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_type: str
    file_name: str
    mime_type: str
    content: str
    source_ids: list[str]
    created_at: datetime


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task: str
    status: str
    step_count: int
    model_name: str | None
    max_steps: int
    max_tokens: int
    max_estimated_cost_cny: float
    used_tokens: int
    estimated_cost_cny: float
    final_result: str | None
    error_type: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[AgentStepResponse] = Field(default_factory=list)
    artifacts: list[AgentArtifactResponse] = Field(default_factory=list)


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    offset: int
    limit: int


class AgentStopResponse(BaseModel):
    status: str
    message: str
