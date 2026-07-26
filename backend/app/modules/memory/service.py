"""提取式滚动摘要与用户显式记忆服务。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import Conversation, Message
from app.modules.memory.models import ConversationSummaryMemory, UserMemory, UserMemorySetting
from app.modules.memory.schemas import (
    MemorySettingResponse,
    UserMemoryListResponse,
    UserMemoryResponse,
    UserMemoryWrite,
)


class MemoryNotFoundError(AppError):
    def __init__(self):
        super().__init__("未找到指定记忆", code="MEMORY_NOT_FOUND", status_code=404)


class ConversationMemoryService:
    def __init__(self, session: Session, *, recent_message_count: int = 6, max_summary_chars: int = 3000):
        self.session = session
        self.recent_message_count = recent_message_count
        self.max_summary_chars = max_summary_chars

    def context_prefixes(self, user_id: str, conversation_id: str) -> list[tuple[str, str]]:
        self._refresh_summary(user_id, conversation_id)
        prefixes = []
        summary = self.session.get(ConversationSummaryMemory, conversation_id)
        if summary:
            prefixes.append(("assistant", f"较早对话摘要：{summary.summary}"))
        setting = self.session.get(UserMemorySetting, user_id)
        if setting and setting.enabled:
            memories = self.session.scalars(
                select(UserMemory).where(UserMemory.user_id == user_id).order_by(UserMemory.updated_at).limit(20)
            ).all()
            if memories:
                text = "；".join(f"{item.label}：{item.content}" for item in memories)
                prefixes.append(("user", f"用户主动保存的背景信息：{text[:2000]}"))
        return prefixes

    def _refresh_summary(self, user_id: str, conversation_id: str) -> None:
        owned = self.session.scalar(
            select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        if owned is None:
            return
        max_sequence = self.session.scalar(
            select(func.max(Message.sequence)).where(
                Message.conversation_id == conversation_id,
                Message.status.in_(("completed", "stopped")),
            )
        ) or 0
        cutoff = max_sequence - self.recent_message_count
        if cutoff <= 0:
            return
        current = self.session.get(ConversationSummaryMemory, conversation_id)
        after = current.summarized_through_sequence if current else 0
        rows = self.session.scalars(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.sequence > after,
                Message.sequence <= cutoff,
                Message.status.in_(("completed", "stopped")),
            ).order_by(Message.sequence)
        ).all()
        if not rows:
            return
        addition = "\n".join(
            f"{'用户' if item.role == 'user' else '助手'}：{item.content[:500]}" for item in rows if item.content
        )
        combined = "\n".join(filter(None, [current.summary if current else "", addition]))
        if current is None:
            current = ConversationSummaryMemory(
                conversation_id=conversation_id,
                summary=combined[-self.max_summary_chars:],
                summarized_through_sequence=cutoff,
            )
            self.session.add(current)
        else:
            current.summary = combined[-self.max_summary_chars:]
            current.summarized_through_sequence = cutoff
        self.session.commit()


class UserMemoryService:
    def __init__(self, session: Session):
        self.session = session

    def get_setting(self, user_id: str):
        setting = self.session.get(UserMemorySetting, user_id)
        return MemorySettingResponse(enabled=bool(setting and setting.enabled))

    def update_setting(self, user_id: str, enabled: bool):
        setting = self.session.get(UserMemorySetting, user_id)
        if setting is None:
            setting = UserMemorySetting(user_id=user_id, enabled=enabled)
            self.session.add(setting)
        else:
            setting.enabled = enabled
        self.session.commit()
        return MemorySettingResponse(enabled=enabled)

    def list(self, user_id: str):
        items = self.session.scalars(
            select(UserMemory).where(UserMemory.user_id == user_id).order_by(UserMemory.updated_at.desc())
        ).all()
        return UserMemoryListResponse(items=[UserMemoryResponse.model_validate(item) for item in items])

    def create(self, user_id: str, payload: UserMemoryWrite):
        memory = UserMemory(user_id=user_id, label=payload.label, content=payload.content)
        self.session.add(memory); self.session.commit(); self.session.refresh(memory)
        return UserMemoryResponse.model_validate(memory)

    def update(self, user_id: str, memory_id: str, payload: UserMemoryWrite):
        memory = self._owned(user_id, memory_id)
        memory.label = payload.label; memory.content = payload.content
        self.session.commit(); self.session.refresh(memory)
        return UserMemoryResponse.model_validate(memory)

    def delete(self, user_id: str, memory_id: str):
        memory = self._owned(user_id, memory_id)
        self.session.delete(memory); self.session.commit()

    def _owned(self, user_id: str, memory_id: str):
        memory = self.session.scalar(
            select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == user_id)
        )
        if memory is None:
            raise MemoryNotFoundError()
        return memory
