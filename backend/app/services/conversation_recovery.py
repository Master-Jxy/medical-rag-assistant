"""收敛进程中断后遗留的 RAG 会话消息。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Conversation, Message


RAG_PROCESS_RESTARTED = "RAG_PROCESS_RESTARTED"
RAG_INTERRUPTED_MESSAGE = "RAG进程中断，本轮回答未正常结束，请重新提问。"


class ConversationRecoveryService:
    """只恢复足够陈旧的 pending 助手消息，避免误伤仍在生成的请求。"""

    def __init__(self, session: Session, recovery_age_seconds: int = 900) -> None:
        self.session = session
        self.recovery_age_seconds = recovery_age_seconds

    def recover_interrupted(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.recovery_age_seconds
        )
        messages = list(
            self.session.scalars(
                select(Message)
                .where(
                    Message.role == "assistant",
                    Message.status == "pending",
                    Message.created_at <= cutoff,
                )
                .with_for_update()
            ).all()
        )
        if not messages:
            return 0

        conversations: dict[str, Conversation] = {}
        for message in messages:
            message.status = "failed"
            message.content = RAG_INTERRUPTED_MESSAGE
            conversation = message.conversation
            if conversation is not None:
                conversations[conversation.id] = conversation

        now = datetime.now(timezone.utc)
        for conversation in conversations.values():
            conversation.updated_at = now

        try:
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise
        return len(messages)
