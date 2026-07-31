"""跨RAG/Agent消息表的只读记忆来源适配器。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.modules.agent.thread_models import AgentMessage, AgentThread


class SqlAlchemyMemorySourceReader:
    def __init__(self, session: Session):
        self.session = session

    def read_completed(
        self,
        *,
        user_id: str,
        surface: str,
        thread_id: str,
        through_sequence: int,
    ) -> list[dict[str, str]]:
        if surface == "rag":
            owned = self.session.scalar(select(Conversation.id).where(
                Conversation.id == thread_id, Conversation.user_id == user_id))
            if owned is None:
                return []
            rows = self.session.scalars(select(Message).where(
                Message.conversation_id == thread_id,
                Message.sequence <= through_sequence,
                Message.status.in_(("completed", "stopped")),
            ).order_by(Message.sequence)).all()
            return [{"id": row.id, "role": row.role, "content": row.content} for row in rows]
        if surface == "agent":
            owned = self.session.scalar(select(AgentThread.id).where(
                AgentThread.id == thread_id, AgentThread.user_id == user_id))
            if owned is None:
                return []
            rows = self.session.scalars(select(AgentMessage).where(
                AgentMessage.thread_id == thread_id,
                AgentMessage.user_id == user_id,
                AgentMessage.sequence_no <= through_sequence,
                AgentMessage.status.in_(("completed", "stopped")),
            ).order_by(AgentMessage.sequence_no)).all()
            return [{"id": row.id, "role": row.role, "content": row.content} for row in rows]
        return []

    def owns_messages(
        self,
        *,
        user_id: str,
        surface: str,
        thread_id: str,
        message_ids: list[str],
    ) -> bool:
        if not message_ids:
            return True
        rows = self.read_completed(
            user_id=user_id, surface=surface, thread_id=thread_id,
            through_sequence=2**63 - 1,
        )
        owned_ids = {row["id"] for row in rows}
        return all(message_id in owned_ids for message_id in message_ids)
