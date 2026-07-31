"""把用户主动启用的长期记忆适配为Agent上下文Port。"""

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.modules.memory.context_provider import SqlAlchemyMemoryContextProvider
from app.modules.memory.models import UserMemory


class SqlAlchemyAgentMemoryContext:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.provider = SqlAlchemyMemoryContextProvider(session)

    def load_enabled_memories(self, user_id: str, *, limit: int) -> list[str]:
        context = self.provider.search(user_id, "", surface="agent")
        ids = [item.id for item in context.items[:limit]]
        if not ids:
            return []
        rows = {row.id: row for row in self.session.scalars(select(UserMemory).where(UserMemory.id.in_(ids))).all()}
        return [f"{rows[item.id].label}：{item.content}" for item in context.items[:limit] if item.id in rows]

    def search(self, user_id: str, question: str):
        return self.provider.search(user_id, question, surface="agent")
