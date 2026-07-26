"""Agent白名单工具的稳定契约。"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class AgentToolArguments(BaseModel):
    """所有工具参数默认拒绝未声明字段。"""

    model_config = ConfigDict(extra="forbid")


class AgentToolResult(BaseModel):
    """只保存用户可理解的结果摘要，不保存隐藏推理过程。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=20)
    artifacts: list["AgentGeneratedArtifact"] = Field(default_factory=list, max_length=5)
    data: dict[str, object] = Field(default_factory=dict)
    used_tokens: int = Field(default=0, ge=0)
    estimated_cost_cny: float = Field(default=0, ge=0)


class AgentGeneratedArtifact(BaseModel):
    """等待应用服务持久化的用户可见产物。"""

    model_config = ConfigDict(extra="forbid")

    artifact_type: str = Field(min_length=1, max_length=50)
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=100_000)
    source_ids: list[str] = Field(default_factory=list, max_length=100)


@dataclass(frozen=True, slots=True)
class AgentToolContext:
    run_id: str
    user_id: str
    task_context: str = ""


class AgentTool(Protocol):
    """工具实现只能依赖公开应用Port，由装配层注入具体能力。"""

    name: str
    description: str
    arguments_model: type[AgentToolArguments]

    def invoke(
        self,
        context: AgentToolContext,
        arguments: AgentToolArguments,
    ) -> AgentToolResult: ...
