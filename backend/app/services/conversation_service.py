"""会话 CRUD 业务：集中处理查询、事务和数据转换。"""

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConversationNotFoundError, ConversationStoreError
from app.models import Conversation, Message
from app.models.conversation import utc_now
from app.schemas.conversation import (
    ConversationDeleteResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    MessageResponse,
)


class ConversationService:
    """对路由隐藏 SQLAlchemy 查询和事务细节。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, title: str) -> ConversationSummary:
        conversation = Conversation(title=title)
        try:
            self.session.add(conversation)
            self.session.commit()
            self.session.refresh(conversation)
            return self._to_summary(conversation, message_count=0)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def list(self, limit: int, offset: int) -> ConversationListResponse:
        message_count = (
            select(func.count(Message.id))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        try:
            total = self.session.scalar(select(func.count()).select_from(Conversation)) or 0
            rows = self.session.execute(
                select(Conversation, message_count.label("message_count"))
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            items = [self._to_summary(conversation, count) for conversation, count in rows]
            return ConversationListResponse(
                conversations=items,
                total=total,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc

    def get_detail(self, conversation_id: str) -> ConversationDetail:
        try:
            conversation = self.session.scalar(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .options(selectinload(Conversation.messages).selectinload(Message.sources))
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if conversation is None:
            raise ConversationNotFoundError()

        messages = [MessageResponse.model_validate(message) for message in conversation.messages]
        return ConversationDetail(
            **self._to_summary(conversation, len(messages)).model_dump(),
            messages=messages,
        )

    def update_title(self, conversation_id: str, title: str) -> ConversationSummary:
        conversation = self._get_or_raise(conversation_id)
        try:
            conversation.title = title
            conversation.updated_at = utc_now()
            self.session.commit()
            self.session.refresh(conversation)
            message_count = self.session.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
            ) or 0
            return self._to_summary(conversation, message_count)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def delete(self, conversation_id: str) -> ConversationDeleteResponse:
        conversation = self._get_or_raise(conversation_id)
        try:
            self.session.delete(conversation)
            self.session.commit()
            return ConversationDeleteResponse(conversation_id=conversation_id)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def _get_or_raise(self, conversation_id: str) -> Conversation:
        try:
            conversation = self.session.get(Conversation, conversation_id)
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    @staticmethod
    def _to_summary(conversation: Conversation, message_count: int) -> ConversationSummary:
        return ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            message_count=message_count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
