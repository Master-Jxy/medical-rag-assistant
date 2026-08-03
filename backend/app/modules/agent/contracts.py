"""Agent白名单工具与受控编排的稳定契约。"""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ResolvedReferences(BaseModel):
    """规划前解析好的显式引用，不包含原始隐藏状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    message_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()


class ToolResultDigest(BaseModel):
    """后续模型可见的有界工具结果，禁止重新发送完整工具正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=64)
    status: str = Field(pattern=r"^(completed|empty|failed|ambiguous)$")
    summary: str = Field(min_length=1, max_length=800)
    source_ids: tuple[str, ...] = ()
    evidence_excerpt: str = Field(default="", max_length=1200)

    @classmethod
    def from_result(
        cls,
        tool_name: str,
        result: "AgentToolResult | None",
    ) -> "ToolResultDigest":
        if result is None:
            return cls(
                tool_name=tool_name,
                status="failed",
                summary="工具未返回可用结果",
            )
        data = result.data if isinstance(result.data, dict) else {}
        items = data.get("items") if isinstance(data, dict) else None
        excerpts: list[str] = []
        if isinstance(items, list):
            remaining = 1200
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, str) or not content.strip():
                    continue
                piece = content.strip()[: min(500, remaining)]
                if piece:
                    excerpts.append(piece)
                    remaining -= len(piece)
                if remaining <= 0:
                    break
        found = data.get("found") if isinstance(data, dict) else None
        count = data.get("count") if isinstance(data, dict) else None
        missing = data.get("missing_document_ids") if isinstance(data, dict) else None
        if found is False or count == 0 or (missing and not result.source_ids):
            status = "empty"
        elif result.source_ids or result.artifacts or excerpts:
            status = "completed"
        else:
            status = "ambiguous"
        return cls(
            tool_name=tool_name,
            status=status,
            summary=result.summary.strip()[:800],
            source_ids=tuple(dict.fromkeys(result.source_ids))[:20],
            evidence_excerpt="\n".join(excerpts)[:1200],
        )


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
    model_calls: int = Field(default=0, ge=0, le=4)


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
