"""把用户主动启用的长期记忆适配为Agent上下文Port。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.memory.models import UserMemory, UserMemorySetting


class SqlAlchemyAgentMemoryContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load_enabled_memories(self, user_id: str, *, limit: int) -> list[str]:
        setting = self.session.get(UserMemorySetting, user_id)
        if setting is None or not setting.enabled:
            return []
        memories = self.session.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
            .limit(limit)
        ).all()
        return [f"{item.label}：{item.content}" for item in memories]
