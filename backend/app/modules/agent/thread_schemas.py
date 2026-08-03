"""Agent会话与消息的持久化契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AgentThreadStatus = Literal["active", "archived"]
AgentAssistantMode = Literal["general", "patient", "clinician", "knowledge"]
AgentThreadRunStatus = Literal["idle", "pending", "running", "stopping"]
AgentMessageRole = Literal["user", "assistant", "system"]
AgentMessageStatus = Literal[
    "pending",
    "streaming",
    "completed",
    "failed",
    "stopped",
]


class AgentThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="新对话", min_length=1, max_length=200)
    assistant_mode: AgentAssistantMode = "general"


class AgentThreadRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)


class AgentThreadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: AgentThreadStatus | None = None
    assistant_mode: AgentAssistantMode | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.title is None and self.status is None and self.assistant_mode is None:
            raise ValueError("至少提供一个会话变更字段")
        return self


class AgentThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: AgentThreadStatus
    assistant_mode: AgentAssistantMode
    last_read_sequence: int
    run_status: AgentThreadRunStatus = "idle"
    active_run_id: str | None = None
    has_unread: bool = False
    last_message_status: AgentMessageStatus | None = None
    summary: str | None
    summary_until_message_id: str | None
    last_message_at: datetime
    created_at: datetime
    updated_at: datetime


class AgentMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentMessageRole
    content: str = Field(default="", max_length=50_000)
    status: AgentMessageStatus = "completed"
    run_id: str | None = None
    reply_to_message_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class AgentMessageStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)
    referenced_message_ids: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)


class AgentThreadListResponse(BaseModel):
    items: list[AgentThreadResponse]
    offset: int
    limit: int


class AgentMessageListResponse(BaseModel):
    items: list["AgentMessageResponse"]
    offset: int
    limit: int


class AgentThreadReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_read_sequence: int = Field(ge=0)


class AgentThreadReadResponse(BaseModel):
    thread_id: str
    last_read_sequence: int


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    thread_id: str
    sequence_no: int
    turn_id: str | None
    role: AgentMessageRole
    content: str
    status: AgentMessageStatus
    run_id: str | None
    reply_to_message_id: str | None
    metadata: dict[str, object] = Field(validation_alias="message_metadata")
    created_at: datetime
    updated_at: datetime
    usage: dict[str, object] | None = None
