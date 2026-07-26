"""会话模块向质量模块提供的最小只读适配器。"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Conversation, Message
from app.modules.quality.ports import ReviewMessageContext


class ConversationQualityQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def user_owns_completed_answer(self, user_id: str, message_id: str) -> bool:
        return (
            self.session.scalar(
                select(Message.id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.id == message_id,
                    Message.role == "assistant",
                    Message.status == "completed",
                    Conversation.user_id == user_id,
                )
            )
            is not None
        )

    def get_review_context(self, message_id: str) -> ReviewMessageContext | None:
        answer = self.session.scalar(
            select(Message)
            .where(Message.id == message_id, Message.role == "assistant")
            .options(selectinload(Message.sources))
        )
        if answer is None:
            return None
        question = self.session.scalar(
            select(Message)
            .where(
                Message.conversation_id == answer.conversation_id,
                Message.role == "user",
                Message.sequence < answer.sequence,
            )
            .order_by(Message.sequence.desc())
            .limit(1)
        )
        return ReviewMessageContext(
            message_id=answer.id,
            conversation_id=answer.conversation_id,
            question_excerpt=(question.content[:1000] if question else ""),
            answer_excerpt=answer.content[:2000],
            source_names=tuple(
                dict.fromkeys(source.file_name for source in answer.sources)
            ),
        )
