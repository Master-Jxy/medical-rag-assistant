"""按预算组合Agent会话上下文，不保存或暴露隐藏推理。"""

import re
from dataclasses import dataclass
from typing import Protocol

from app.modules.agent.contracts import ResolvedReferences
from app.modules.agent.mode_policy import get_mode_policy
from app.modules.agent.public_events import normalize_clarification_key
from app.modules.agent.repository import AgentRepository, AgentRunNotFoundError
from app.modules.agent.thread_models import AgentMessage
from app.modules.agent.thread_repository import (
    AgentMessageNotFoundError,
    AgentThreadRepository,
)

REFERENCED_ARTIFACT_EXCERPT_CHARS = 1200
DOCUMENT_ID_PATTERN = re.compile(
    r"\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|doc-\d+)\b",
    re.IGNORECASE,
)


class AgentMemoryContextPort(Protocol):
    def load_enabled_memories(self, user_id: str, *, limit: int) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class AgentContextBundle:
    rendered: str
    estimated_tokens: int
    included_message_ids: tuple[str, ...]
    included_memory_count: int
    truncated: bool
    assistant_mode: str
    resolved_references: ResolvedReferences
    previous_clarification_key: str | None
    section_tokens: tuple[tuple[str, int], ...]


class NullAgentMemoryContext:
    def load_enabled_memories(self, user_id: str, *, limit: int) -> list[str]:
        del user_id, limit
        return []


class AgentContextBuilder:
    def __init__(
        self,
        threads: AgentThreadRepository,
        runs: AgentRepository,
        memory: AgentMemoryContextPort | None = None,
        *,
        max_tokens: int = 3000,
        recent_message_limit: int = 8,
    ) -> None:
        self.threads = threads
        self.runs = runs
        self.memory = memory or NullAgentMemoryContext()
        self.max_tokens = max_tokens
        self.recent_message_limit = recent_message_limit

    def build(
        self,
        *,
        user_id: str,
        thread_id: str,
        current_message: AgentMessage,
    ) -> AgentContextBundle:
        thread = self.threads.get_thread(user_id, thread_id)
        mode_policy = get_mode_policy(thread.assistant_mode)
        metadata = current_message.message_metadata or {}
        sections: list[tuple[str, str, bool, int]] = [
            ("当前任务", current_message.content, True, 1000),
            ("系统安全约束", mode_policy.safety_context, True, 300),
        ]
        included_ids: list[str] = []
        source_ids = [str(item) for item in metadata.get("source_ids", [])]
        message_ids: list[str] = []
        artifact_ids = [str(item) for item in metadata.get("artifact_ids", [])]
        labels: list[str] = []
        for message_id in metadata.get("referenced_message_ids", []):
            try:
                message = self.threads.get_message(
                    user_id, thread_id, str(message_id)
                )
            except AgentMessageNotFoundError:
                continue
            sections.append(
                (
                    "显式引用消息",
                    f"{message.role}：{message.content}",
                    True,
                    700,
                )
            )
            included_ids.append(message.id)
            message_ids.append(message.id)
            referenced_metadata = message.message_metadata or {}
            source_ids.extend(
                str(item) for item in referenced_metadata.get("source_ids", [])
            )
            for source in referenced_metadata.get("sources", []):
                if not isinstance(source, dict):
                    continue
                document_id = source.get("document_id")
                file_name = source.get("file_name")
                if isinstance(document_id, str):
                    source_ids.append(document_id)
                if isinstance(file_name, str):
                    labels.append(file_name)
            artifact_ids.extend(
                str(item) for item in referenced_metadata.get("artifact_ids", [])
            )
            source_ids.extend(DOCUMENT_ID_PATTERN.findall(message.content))
        if source_ids:
            sections.append(("显式引用来源", "、".join(source_ids), True, 300))
        artifact_lines = []
        resolved_artifact_ids: list[str] = []
        for artifact_id in dict.fromkeys(artifact_ids):
            try:
                artifact = self.runs.get_artifact(user_id, str(artifact_id))
            except AgentRunNotFoundError:
                continue
            excerpt = artifact.content.strip()[:REFERENCED_ARTIFACT_EXCERPT_CHARS]
            artifact_lines.append(
                f"{artifact.file_name}（来源：{'、'.join(artifact.source_ids) or '无'}）"
                f"\n内容摘录：{excerpt}"
            )
            resolved_artifact_ids.append(artifact.id)
            source_ids.extend(str(item) for item in artifact.source_ids)
            labels.append(artifact.file_name)
        if artifact_lines:
            sections.append(
                ("显式引用产物", "\n".join(artifact_lines), True, 900)
            )

        recent = self.threads.list_recent_messages(
            user_id,
            thread_id,
            before_message_id=current_message.id,
            limit=self.recent_message_limit,
        )
        previous_clarification_key = None
        for message in reversed(recent):
            if message.role != "assistant":
                continue
            content = message.content.strip()
            if content.endswith(("?", "？")) or content.startswith(
                ("请提供", "请说明", "请确认", "您是指", "你是指")
            ):
                previous_clarification_key = normalize_clarification_key(content)
                break

        search = getattr(self.memory, "search", None)
        if callable(search):
            memory_context = search(user_id, current_message.content)
            memories = [item.content for item in memory_context.items]
        else:
            memories = self.memory.load_enabled_memories(user_id, limit=20)
        for memory in memories:
            sections.append(("用户显式记忆", memory, False, 500))
        for message in recent:
            sections.append(
                ("最近消息", f"{message.role}：{message.content}", False, 500)
            )
            included_ids.append(message.id)
        if thread.summary:
            sections.append(("更早会话摘要", thread.summary, False, 300))

        rendered: list[str] = []
        used = 0
        truncated = False
        included_memory_count = 0
        section_tokens: list[tuple[str, int]] = []
        for label, content, required, section_limit in sections:
            block = f"[{label}]\n{content.strip()}"
            if self.estimate_tokens(block) > section_limit:
                block = block[: section_limit * 4]
                truncated = True
            cost = self.estimate_tokens(block)
            if used + cost > self.max_tokens and not required:
                truncated = True
                continue
            if used + cost > self.max_tokens:
                remaining_chars = max((self.max_tokens - used) * 4, 0)
                block = block[:remaining_chars]
                cost = self.estimate_tokens(block)
                truncated = True
            if block:
                rendered.append(block)
                used += cost
                section_tokens.append((label, cost))
                if label == "用户显式记忆":
                    included_memory_count += 1
        unique_sources = tuple(dict.fromkeys(item for item in source_ids if item))
        document_ids = tuple(
            item
            for item in unique_sources
            if len(item) <= 36 and DOCUMENT_ID_PATTERN.fullmatch(item)
        )
        resolved = ResolvedReferences(
            source_ids=unique_sources[:100],
            document_ids=document_ids[:20],
            message_ids=tuple(dict.fromkeys(message_ids))[:20],
            artifact_ids=tuple(dict.fromkeys(resolved_artifact_ids))[:20],
            labels=tuple(dict.fromkeys(labels))[:20],
        )
        return AgentContextBundle(
            rendered="\n\n".join(rendered),
            estimated_tokens=used,
            included_message_ids=tuple(dict.fromkeys(included_ids)),
            included_memory_count=included_memory_count,
            truncated=truncated,
            assistant_mode=thread.assistant_mode,
            resolved_references=resolved,
            previous_clarification_key=previous_clarification_key,
            section_tokens=tuple(section_tokens),
        )

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)
