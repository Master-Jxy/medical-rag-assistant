"""会话 CRUD 业务：集中处理查询、事务和数据转换。"""

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConversationNotFoundError, ConversationStoreError
from app.models import Conversation, Message
from app.modules.usage.models import ModelUsageRecord
from app.models.conversation import utc_now
from app.schemas.conversation import (
    ConversationDeleteResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationReadResponse,
    ConversationSummary,
    MessageResponse,
)
from app.services.generation_lock_service import (
    ConversationGenerationInProgressError,
)


class ConversationService:
    """对路由隐藏 SQLAlchemy 查询和事务细节。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, user_id: str, title: str) -> ConversationSummary:
        conversation = Conversation(user_id=user_id, title=title)
        try:
            self.session.add(conversation)
            self.session.commit()
            self.session.refresh(conversation)
            return self._to_summary(conversation, message_count=0)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def list(self, user_id: str, limit: int, offset: int) -> ConversationListResponse:
        try:
            total = self.session.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.user_id == user_id)
            ) or 0
            rows = self.session.execute(
                self._summary_statement(user_id)
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            items = [
                self._to_summary(
                    conversation,
                    message_count,
                    last_message_status=last_message_status,
                    has_unread=bool(has_unread),
                    has_active_message=bool(has_active_message),
                    active_request_id=active_request_id,
                )
                for (
                    conversation,
                    message_count,
                    last_message_status,
                    has_unread,
                    has_active_message,
                    active_request_id,
                ) in rows
            ]
            return ConversationListResponse(
                conversations=items,
                total=total,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc

    def get_detail(self, user_id: str, conversation_id: str) -> ConversationDetail:
        try:
            conversation = self.session.scalar(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
                .options(selectinload(Conversation.messages).selectinload(Message.sources))
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if conversation is None:
            raise ConversationNotFoundError()

        usage_rows = self.session.scalars(select(ModelUsageRecord).where(
            ModelUsageRecord.usage_group_id.in_([m.id for m in conversation.messages])
        )).all()
        usage_by_message = {}
        for row in usage_rows:
            usage_by_message.setdefault(row.usage_group_id, []).append(row)
        messages = []
        for message in conversation.messages:
            payload = MessageResponse.model_validate(message).model_dump()
            rows = usage_by_message.get(message.id, [])
            if rows:
                if any(row.token_measurement == "unknown" for row in rows):
                    payload["usage"] = {"measurement": "unknown"}
                elif any(row.token_measurement == "actual" for row in rows):
                    actual = [row for row in rows if row.token_measurement == "actual"]
                    payload["usage"] = {"measurement": "actual", "input_tokens": sum(row.input_tokens or 0 for row in actual),
                        "output_tokens": sum(row.output_tokens or 0 for row in actual), "total_tokens": sum(row.total_tokens or 0 for row in actual),
                        "estimated_cost_cny": float(sum(row.estimated_cost_cny for row in actual)) if all(row.estimated_cost_cny is not None for row in actual) else None}
                else:
                    payload["usage"] = {"measurement": "not_applicable", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated_cost_cny": 0}
            messages.append(MessageResponse.model_validate(payload))
        return ConversationDetail(
            **self._to_summary(
                conversation,
                len(messages),
                last_message_status=(messages[-1].status if messages else None),
                has_unread=any(
                    message.role == "assistant"
                    and message.status in {"completed", "failed", "stopped"}
                    and message.sequence > conversation.last_read_sequence
                    for message in messages
                ),
                has_active_message=any(
                    message.role == "assistant" and message.status == "pending"
                    for message in conversation.messages
                ),
                active_request_id=next(
                    (
                        message.request_id
                        for message in conversation.messages
                        if message.role == "assistant"
                        and message.status == "pending"
                        and message.request_id
                    ),
                    None,
                ),
            ).model_dump(),
            messages=messages,
        )

    def update_title(
        self, user_id: str, conversation_id: str, title: str
    ) -> ConversationSummary:
        conversation = self._get_or_raise(user_id, conversation_id)
        try:
            conversation.title = title
            conversation.updated_at = utc_now()
            self.session.commit()
            return self._get_summary_or_raise(user_id, conversation_id)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def mark_read(
        self,
        user_id: str,
        conversation_id: str,
        last_read_sequence: int,
    ) -> ConversationReadResponse:
        self._get_or_raise(user_id, conversation_id)
        try:
            latest_sequence = self.session.scalar(
                select(func.coalesce(func.max(Message.sequence), 0)).where(
                    Message.conversation_id == conversation_id
                )
            ) or 0
            target = min(last_read_sequence, int(latest_sequence))
            self.session.execute(
                update(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
                .values(
                    last_read_sequence=case(
                        (Conversation.last_read_sequence < target, target),
                        else_=Conversation.last_read_sequence,
                    )
                )
                .execution_options(synchronize_session=False)
            )
            self.session.commit()
            marker = self.session.scalar(
                select(Conversation.last_read_sequence).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            return ConversationReadResponse(
                conversation_id=conversation_id,
                last_read_sequence=int(marker or 0),
            )
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def delete(self, user_id: str, conversation_id: str) -> ConversationDeleteResponse:
        try:
            conversation = self.session.scalar(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
                .with_for_update()
            )
            if conversation is None:
                raise ConversationNotFoundError()
            has_pending = self.session.scalar(
                select(
                    exists().where(
                        Message.conversation_id == conversation_id,
                        Message.role == "assistant",
                        Message.status == "pending",
                    )
                )
            )
            if has_pending:
                self.session.rollback()
                raise ConversationGenerationInProgressError()
            self.session.delete(conversation)
            self.session.commit()
            return ConversationDeleteResponse(conversation_id=conversation_id)
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def _get_or_raise(self, user_id: str, conversation_id: str) -> Conversation:
        try:
            conversation = self.session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    def _get_summary_or_raise(
        self, user_id: str, conversation_id: str
    ) -> ConversationSummary:
        try:
            row = self.session.execute(
                self._summary_statement(user_id).where(
                    Conversation.id == conversation_id
                )
            ).one_or_none()
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if row is None:
            raise ConversationNotFoundError()
        (
            conversation,
            count,
            last_status,
            has_unread,
            has_active_message,
            active_request_id,
        ) = row
        return self._to_summary(
            conversation,
            count,
            last_message_status=last_status,
            has_unread=bool(has_unread),
            has_active_message=bool(has_active_message),
            active_request_id=active_request_id,
        )

    @staticmethod
    def _summary_statement(user_id: str):
        message_count = (
            select(func.count(Message.id))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        last_message_status = (
            select(Message.status)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.sequence.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        has_unread = exists(
            select(Message.id).where(
                Message.conversation_id == Conversation.id,
                Message.role == "assistant",
                Message.status.in_(("completed", "failed", "stopped")),
                Message.sequence > Conversation.last_read_sequence,
            )
        ).correlate(Conversation)
        active_request_id = (
            select(Message.request_id).where(
                Message.conversation_id == Conversation.id,
                Message.role == "assistant",
                Message.status == "pending",
                Message.request_id.is_not(None),
            )
            .order_by(Message.sequence.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        has_active_message = exists(
            select(Message.id).where(
                Message.conversation_id == Conversation.id,
                Message.role == "assistant",
                Message.status == "pending",
            )
        ).correlate(Conversation)
        return select(
            Conversation,
            message_count.label("message_count"),
            last_message_status.label("last_message_status"),
            has_unread.label("has_unread"),
            has_active_message.label("has_active_message"),
            active_request_id.label("active_request_id"),
        ).where(Conversation.user_id == user_id)

    @staticmethod
    def _to_summary(
        conversation: Conversation,
        message_count: int,
        *,
        last_message_status: str | None = None,
        has_unread: bool = False,
        has_active_message: bool = False,
        active_request_id: str | None = None,
    ) -> ConversationSummary:
        return ConversationSummary(
            id=conversation.id,
            title=conversation.title,
            message_count=message_count,
            last_read_sequence=conversation.last_read_sequence,
            run_status="pending" if has_active_message else "idle",
            active_run_id=active_request_id,
            has_unread=has_unread,
            last_message_status=last_message_status,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
