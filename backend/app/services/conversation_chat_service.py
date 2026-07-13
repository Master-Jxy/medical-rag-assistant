"""把一次普通 RAG 问答可靠地写入会话历史。"""

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    AppError,
    ConversationNotFoundError,
    ConversationStoreError,
    RagServiceError,
)
from app.models import Conversation, Message, MessageSource
from app.models.conversation import utc_now
from app.schemas.chat import SourceItem
from app.schemas.conversation import ConversationChatResponse
from app.services.rag_service import RagService


class ConversationChatService:
    """协调数据库和 RAG；不把 SQL 事务放进 API 路由。"""

    def __init__(self, session: Session, rag_service: RagService) -> None:
        self.session = session
        self.rag_service = rag_service
        settings = get_settings()
        self.max_history_messages = settings.max_history_rounds * 2
        self.max_history_chars = settings.max_history_chars

    def ask(self, conversation_id: str, question: str, top_k: int) -> ConversationChatResponse:
        request_id = str(uuid4())
        history = self._load_recent_history(conversation_id)
        user_message, assistant_message = self._create_pending_messages(
            conversation_id,
            question,
            request_id,
        )

        try:
            answer, sources = self.rag_service.ask(question, top_k, history=history)
        except AppError:
            self._mark_failed(conversation_id, assistant_message.id, request_id)
            raise
        except Exception as exc:
            self._mark_failed(conversation_id, assistant_message.id, request_id)
            raise RagServiceError() from exc

        self._finish_message(
            conversation_id,
            assistant_message.id,
            request_id,
            content=answer,
            status="completed",
            sources=sources,
        )
        return ConversationChatResponse(
            answer=answer,
            sources=sources,
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )

    def stream(self, conversation_id: str, question: str, top_k: int, request_id: str):
        """产生 SSE 业务事件，并在结束、失败或关闭时更新消息状态。"""
        history = self._load_recent_history(conversation_id)
        user_message, assistant_message = self._create_pending_messages(
            conversation_id,
            question,
            request_id,
        )
        answer_parts: list[str] = []
        sources: list[SourceItem] = []

        try:
            for item in self.rag_service.stream_ask(question, top_k, history=history):
                if item["event"] == "token":
                    answer_parts.append(item["data"].get("content", ""))
                elif item["event"] == "sources":
                    sources = [
                        SourceItem.model_validate(source)
                        for source in item["data"].get("sources", [])
                    ]
                yield item

        except GeneratorExit:
            self._finish_message(
                conversation_id,
                assistant_message.id,
                request_id,
                content="".join(answer_parts),
                status="stopped",
                sources=[],
            )
            raise
        except AppError:
            self._finish_message(
                conversation_id,
                assistant_message.id,
                request_id,
                content="".join(answer_parts),
                status="failed",
                sources=[],
            )
            raise
        except Exception as exc:
            self._finish_message(
                conversation_id,
                assistant_message.id,
                request_id,
                content="".join(answer_parts),
                status="failed",
                sources=[],
            )
            raise RagServiceError() from exc

        self._finish_message(
            conversation_id,
            assistant_message.id,
            request_id,
            content="".join(answer_parts),
            status="completed",
            sources=sources,
        )
        # done 在完成事务之后发送；收到 done 就代表历史记录已经可读取。
        yield {
            "event": "done",
            "data": {
                "request_id": request_id,
                "conversation_id": conversation_id,
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "disclaimer": "仅供学习和信息检索，不构成医疗建议。",
            },
        }

    def _create_pending_messages(
        self,
        conversation_id: str,
        question: str,
        request_id: str,
    ) -> tuple[Message, Message]:
        try:
            # 锁住会话行，避免两个并发请求拿到相同 sequence。
            conversation = self.session.scalar(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .with_for_update()
            )
            if conversation is None:
                raise ConversationNotFoundError()

            max_sequence = self.session.scalar(
                select(func.max(Message.sequence)).where(
                    Message.conversation_id == conversation_id
                )
            ) or 0
            user_message = Message(
                conversation_id=conversation_id,
                sequence=max_sequence + 1,
                role="user",
                content=question,
                status="completed",
            )
            assistant_message = Message(
                conversation_id=conversation_id,
                sequence=max_sequence + 2,
                role="assistant",
                content="",
                status="pending",
                request_id=request_id,
            )
            if conversation.title == "新对话":
                conversation.title = self._title_from_question(question)
            conversation.updated_at = utc_now()
            self.session.add_all([user_message, assistant_message])
            # 第一段事务先提交，模型失败时仍能保留用户问题和失败事实。
            self.session.commit()
            return user_message, assistant_message
        except AppError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    def _load_recent_history(self, conversation_id: str) -> list[tuple[str, str]]:
        """读取最近3轮可用消息，并从最近消息开始应用字符预算。"""
        try:
            rows = self.session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.status.in_(("completed", "stopped")),
                )
                .order_by(Message.sequence.desc())
                .limit(self.max_history_messages)
            ).all()
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc

        selected: list[tuple[str, str]] = []
        remaining_chars = self.max_history_chars
        for message in rows:
            if remaining_chars <= 0:
                break
            content = message.content[:remaining_chars]
            if content:
                selected.append((message.role, content))
                remaining_chars -= len(content)
        selected.reverse()
        return selected

    def _mark_failed(self, conversation_id: str, assistant_message_id: str, request_id: str) -> None:
        self._finish_message(
            conversation_id,
            assistant_message_id,
            request_id,
            content="",
            status="failed",
            sources=[],
        )

    def _finish_message(
        self,
        conversation_id: str,
        assistant_message_id: str,
        request_id: str,
        *,
        content: str,
        status: str,
        sources: list[SourceItem],
    ) -> None:
        try:
            assistant_message = self.session.get(Message, assistant_message_id)
            conversation = self.session.get(Conversation, conversation_id)
            if assistant_message is None or conversation is None:
                raise ConversationStoreError()
            assistant_message.content = content
            assistant_message.status = status
            assistant_message.request_id = request_id
            assistant_message.sources = [
                MessageSource(
                    position=index,
                    file_name=source.file_name,
                    page=source.page,
                    content=source.content,
                )
                for index, source in enumerate(sources, start=1)
            ]
            conversation.updated_at = utc_now()
            self.session.commit()
        except AppError:
            self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ConversationStoreError() from exc

    @staticmethod
    def _title_from_question(question: str) -> str:
        return question[:30] + ("…" if len(question) > 30 else "")
