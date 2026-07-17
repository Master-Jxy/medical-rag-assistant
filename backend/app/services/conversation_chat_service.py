"""把一次 RAG 问答可靠地写入会话历史。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
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
from app.services.generation_lock_service import GenerationLockService
from app.ports.idempotency import IdempotencyRecord
from app.services.idempotency_service import IdempotencyService
from app.services.stream_cancellation_service import StreamCancellationService


class ConversationChatService:
    """协调数据库和 RAG；不把 SQL 事务放进 API 路由。"""

    def __init__(
        self,
        session: Session,
        rag_service: RagService,
        generation_lock: GenerationLockService,
        idempotency: IdempotencyService,
        cancellation: StreamCancellationService | None = None,
    ) -> None:
        self.session = session
        self.rag_service = rag_service
        self.generation_lock = generation_lock
        self.idempotency = idempotency
        self.cancellation = cancellation or StreamCancellationService()
        settings = get_settings()
        self.max_history_messages = settings.max_history_rounds * 2
        self.max_history_chars = settings.max_history_chars

    def ask(
        self,
        user_id: str,
        conversation_id: str,
        question: str,
        top_k: int,
        client_request_id: str,
    ) -> ConversationChatResponse:
        request_id = str(uuid4())
        self._assert_conversation_owned(user_id, conversation_id)
        claim = self.idempotency.begin(
            user_id,
            "chat",
            client_request_id,
            conversation_id,
            question,
            top_k,
        )
        if claim.completed_record is not None:
            return self._load_completed_response(
                user_id, conversation_id, claim.completed_record
            )

        lease = None
        completed = False
        answer_persisted = False
        try:
            lease = self.generation_lock.acquire(user_id, conversation_id)
            history = self._load_recent_history(user_id, conversation_id)
            user_message, assistant_message = self._create_pending_messages(
                user_id, conversation_id, question, request_id
            )
            try:
                answer, sources = self.rag_service.ask(question, top_k, history=history)
            except AppError:
                self._mark_failed(
                    user_id, conversation_id, assistant_message.id, request_id
                )
                raise
            except Exception as exc:
                self._mark_failed(
                    user_id, conversation_id, assistant_message.id, request_id
                )
                raise RagServiceError() from exc

            self._finish_message(
                user_id,
                conversation_id,
                assistant_message.id,
                request_id,
                content=answer,
                status="completed",
                sources=sources,
            )
            answer_persisted = True
            response = ConversationChatResponse(
                answer=answer,
                sources=sources,
                request_id=request_id,
                conversation_id=conversation_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
            self.idempotency.complete(
                claim,
                request_id=request_id,
                conversation_id=conversation_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
            completed = True
            return response
        finally:
            if not completed and not answer_persisted:
                self.idempotency.abandon(claim)
            if lease is not None:
                self.generation_lock.release(lease)

    def stream(
        self,
        user_id: str,
        conversation_id: str,
        question: str,
        top_k: int,
        request_id: str,
        client_request_id: str,
    ):
        """先同步校验归属，再返回 SSE 迭代器，越权请求因此能直接返回404。"""
        self._assert_conversation_owned(user_id, conversation_id)
        claim = self.idempotency.begin(
            user_id,
            "chat-stream",
            client_request_id,
            conversation_id,
            question,
            top_k,
        )
        if claim.completed_record is not None:
            response = self._load_completed_response(
                user_id, conversation_id, claim.completed_record
            )
            return self._replay_completed_stream(response)

        lease = None
        cancellation_lease = None
        try:
            lease = self.generation_lock.acquire(user_id, conversation_id)
            history = self._load_recent_history(user_id, conversation_id)
            user_message, assistant_message = self._create_pending_messages(
                user_id, conversation_id, question, request_id
            )
            cancellation_lease = self.cancellation.register(
                user_id, conversation_id, client_request_id
            )
        except BaseException:
            self.idempotency.abandon(claim)
            if lease is not None:
                self.generation_lock.release(lease)
            raise

        async def event_iterator():
            answer_parts: list[str] = []
            sources: list[SourceItem] = []
            completed = False
            answer_persisted = False

            rag_iterator = self._async_rag_stream(question, top_k, history)
            try:
                while True:
                    next_item = asyncio.create_task(anext(rag_iterator))
                    while not next_item.done() and not cancellation_lease.event.is_set():
                        await asyncio.sleep(0.05)
                    if cancellation_lease.event.is_set():
                        next_item.cancel()
                        with suppress(asyncio.CancelledError):
                            await next_item
                        await rag_iterator.aclose()
                        break
                    try:
                        item = await next_item
                    except StopAsyncIteration:
                        break
                    if item["event"] == "token":
                        answer_parts.append(item["data"].get("content", ""))
                    elif item["event"] == "sources":
                        sources = [
                            SourceItem.model_validate(source)
                            for source in item["data"].get("sources", [])
                        ]
                    yield item

                if cancellation_lease.event.is_set():
                    self._finish_message(
                        user_id,
                        conversation_id,
                        assistant_message.id,
                        request_id,
                        content="".join(answer_parts),
                        status="stopped",
                        sources=[],
                    )
                    yield {
                        "event": "stopped",
                        "data": {
                            "message": "已停止生成。",
                            "request_id": request_id,
                            "user_message_id": user_message.id,
                            "assistant_message_id": assistant_message.id,
                        },
                    }
                    return

            except (GeneratorExit, asyncio.CancelledError):
                await rag_iterator.aclose()
                self._finish_message(
                    user_id,
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
                    user_id,
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
                    user_id,
                    conversation_id,
                    assistant_message.id,
                    request_id,
                    content="".join(answer_parts),
                    status="failed",
                    sources=[],
                )
                raise RagServiceError() from exc
            else:
                self._finish_message(
                    user_id,
                    conversation_id,
                    assistant_message.id,
                    request_id,
                    content="".join(answer_parts),
                    status="completed",
                    sources=sources,
                )
                answer_persisted = True
                self.idempotency.complete(
                    claim,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                )
                completed = True
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
            finally:
                if not completed and not answer_persisted:
                    self.idempotency.abandon(claim)
                if cancellation_lease is not None:
                    self.cancellation.unregister(cancellation_lease)
                self.generation_lock.release(lease)

        return event_iterator()

    async def _async_rag_stream(
        self,
        question: str,
        top_k: int,
        history: list[tuple[str, str]],
    ) -> AsyncIterator[dict]:
        """生产环境走原生异步流；同步测试替身保持兼容。"""
        async_stream = getattr(self.rag_service, "astream_ask", None)
        if async_stream is not None:
            async for item in async_stream(question, top_k, history=history):
                yield item
            return
        for item in self.rag_service.stream_ask(question, top_k, history=history):
            yield item

    def _load_completed_response(
        self,
        user_id: str,
        conversation_id: str,
        record: IdempotencyRecord,
    ) -> ConversationChatResponse:
        """Redis 只给出资源 ID，完整回答始终从 MySQL 恢复。"""
        try:
            conversation = self.session.scalar(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            user_message = self.session.scalar(
                select(Message).where(
                    Message.id == record.user_message_id,
                    Message.conversation_id == conversation_id,
                    Message.role == "user",
                )
            )
            assistant_message = self.session.scalar(
                select(Message).where(
                    Message.id == record.assistant_message_id,
                    Message.conversation_id == conversation_id,
                    Message.role == "assistant",
                    Message.status == "completed",
                )
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if conversation is None or user_message is None or assistant_message is None:
            raise ConversationStoreError()
        sources = [
            SourceItem(
                file_name=source.file_name,
                page=source.page,
                content=source.content,
            )
            for source in assistant_message.sources
        ]
        return ConversationChatResponse(
            answer=assistant_message.content,
            sources=sources,
            request_id=record.request_id or assistant_message.request_id or "",
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )

    @staticmethod
    async def _replay_completed_stream(response: ConversationChatResponse):
        """重复 SSE 请求用 MySQL 结果产生一次可解析的稳定回放。"""
        yield {"event": "token", "data": {"content": response.answer}}
        if response.sources:
            yield {
                "event": "sources",
                "data": {
                    "sources": [source.model_dump() for source in response.sources]
                },
            }
        yield {
            "event": "done",
            "data": {
                "request_id": response.request_id,
                "conversation_id": response.conversation_id,
                "user_message_id": response.user_message_id,
                "assistant_message_id": response.assistant_message_id,
                "disclaimer": response.disclaimer,
            },
        }

    def _assert_conversation_owned(self, user_id: str, conversation_id: str) -> None:
        try:
            owned_conversation_id = self.session.scalar(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
        except SQLAlchemyError as exc:
            raise ConversationStoreError() from exc
        if owned_conversation_id is None:
            raise ConversationNotFoundError()

    def _create_pending_messages(
        self,
        user_id: str,
        conversation_id: str,
        question: str,
        request_id: str,
    ) -> tuple[Message, Message]:
        try:
            # 锁住会话行，避免两个并发请求拿到相同 sequence。
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

    def _load_recent_history(
        self, user_id: str, conversation_id: str
    ) -> list[tuple[str, str]]:
        """读取最近3轮可用消息，并从最近消息开始应用字符预算。"""
        try:
            owned_conversation_id = self.session.scalar(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            if owned_conversation_id is None:
                raise ConversationNotFoundError()
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

    def _mark_failed(
        self,
        user_id: str,
        conversation_id: str,
        assistant_message_id: str,
        request_id: str,
    ) -> None:
        self._finish_message(
            user_id,
            conversation_id,
            assistant_message_id,
            request_id,
            content="",
            status="failed",
            sources=[],
        )

    def _finish_message(
        self,
        user_id: str,
        conversation_id: str,
        assistant_message_id: str,
        request_id: str,
        *,
        content: str,
        status: str,
        sources: list[SourceItem],
    ) -> None:
        try:
            assistant_message = self.session.scalar(
                select(Message).where(
                    Message.id == assistant_message_id,
                    Message.conversation_id == conversation_id,
                )
            )
            conversation = self.session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
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
