"""带会话流式问答的 completed、failed、stopped 状态测试。"""

import asyncio
from time import perf_counter

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import RagServiceError
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation
from app.modules.auth.tokens import get_token_service
from app.services.conversation_chat_service import ConversationChatService
from app.services.conversation_service import ConversationService
from app.services.rag_service import get_rag_service
from app.services.generation_lock_service import (
    ConversationGenerationInProgressError,
    GenerationLockLease,
    GenerationLockUnavailableError,
    get_generation_lock_service,
)
from app.services.idempotency_service import get_idempotency_service
from app.services.stream_cancellation_service import (
    StreamCancellationService,
    get_stream_cancellation_service,
)
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.idempotency_helpers import AllowingIdempotency


class SuccessfulStreamRagService:
    def stream_ask(self, question: str, top_k: int, history=None):
        yield {"event": "token", "data": {"content": "流式"}}
        yield {"event": "token", "data": {"content": "回答"}}
        yield {
            "event": "sources",
            "data": {
                "sources": [
                    {"file_name": "指南.pdf", "page": 8, "content": "引用原文"}
                ]
            },
        }


class FailingStreamRagService:
    def stream_ask(self, question: str, top_k: int, history=None):
        yield {"event": "token", "data": {"content": "部分回答"}}
        raise RagServiceError("测试流中错误")


class StoppableStreamRagService:
    def stream_ask(self, question: str, top_k: int, history=None):
        yield {"event": "token", "data": {"content": "已生成部分"}}
        yield {"event": "token", "data": {"content": "不应到达"}}


class BlockingAsyncStreamRagService:
    """模拟模型已经返回首块、随后长时间等待下一块。"""

    def __init__(self) -> None:
        self.cancelled = False
        self.blocked = asyncio.Event()

    async def astream_ask(self, question: str, top_k: int, history=None):
        yield {"event": "token", "data": {"content": "已生成部分"}}
        try:
            self.blocked.set()
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield {"event": "token", "data": {"content": "不应到达"}}


class NeverCalledRagService:
    def ask(self, question: str, top_k: int, history=None):
        raise AssertionError("越权普通问答不应调用 RAG")

    def stream_ask(self, question: str, top_k: int, history=None):
        raise AssertionError("越权流式问答不应调用 RAG")


class AllowingGenerationLock:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self, user_id: str, conversation_id: str) -> GenerationLockLease:
        self.acquired += 1
        return GenerationLockLease("test-lock", f"owner-{self.acquired}")

    def release(self, lease: GenerationLockLease) -> None:
        self.released += 1


class RejectingGenerationLock:
    def __init__(self, error) -> None:
        self.error = error

    def acquire(self, user_id: str, conversation_id: str):
        raise self.error


def build_test_database(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'stream-chat.db'}")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    user = create_test_user(factory, "stream-owner")
    return engine, factory, override_session, user


def test_completed_stream_saves_answer_sources_and_done_ids(tmp_path) -> None:
    engine, _, override_session, user = build_test_database(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: SuccessfulStreamRagService()
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    generation_lock = AllowingGenerationLock()
    idempotency = AllowingIdempotency()
    app.dependency_overrides[get_generation_lock_service] = lambda: generation_lock
    app.dependency_overrides[get_idempotency_service] = lambda: idempotency
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "流式成功测试", "top_k": 2},
                headers={
                    **auth_headers(user.id),
                    "Idempotency-Key": "stream-success",
                },
            )
            assert response.status_code == 200
            assert response.text.count("event: token") == 2
            assert "event: sources" in response.text
            assert "event: done" in response.text
            assert "assistant_message_id" in response.text

            detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(user.id),
            ).json()
            assistant = detail["messages"][1]
            assert assistant["status"] == "completed"
            assert assistant["content"] == "流式回答"
            assert assistant["sources"][0]["file_name"] == "指南.pdf"
            assert generation_lock.released == 1
            assert idempotency.completed == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_failed_stream_saves_partial_content_without_sources(tmp_path) -> None:
    engine, _, override_session, user = build_test_database(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: FailingStreamRagService()
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    generation_lock = AllowingGenerationLock()
    idempotency = AllowingIdempotency()
    app.dependency_overrides[get_generation_lock_service] = lambda: generation_lock
    app.dependency_overrides[get_idempotency_service] = lambda: idempotency
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=auth_headers(user.id),
            ).json()["id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "流式失败测试", "top_k": 2},
                headers={
                    **auth_headers(user.id),
                    "Idempotency-Key": "stream-failure",
                },
            )
            assert "event: error" in response.text
            assert "测试流中错误" in response.text

            detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(user.id),
            ).json()
            assistant = detail["messages"][1]
            assert assistant["status"] == "failed"
            assert assistant["content"] == "部分回答"
            assert assistant["sources"] == []
            assert generation_lock.released == 1
            assert idempotency.abandoned == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_closing_stream_marks_assistant_stopped_and_keeps_partial_content(tmp_path) -> None:
    engine, factory, _, user = build_test_database(tmp_path)
    try:
        with factory() as session:
            conversation = Conversation(user_id=user.id, title="新对话")
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id

            generation_lock = AllowingGenerationLock()
            idempotency = AllowingIdempotency()
            generator = ConversationChatService(
                session,
                StoppableStreamRagService(),
                generation_lock,
                idempotency,
            ).stream(
                user.id,
                conversation_id,
                "主动停止测试",
                2,
                "stopped-request-id",
                "stream-stopped",
            )
            async def close_after_first_event() -> None:
                first_event = await anext(generator)
                assert first_event["data"]["content"] == "已生成部分"
                await generator.aclose()

            asyncio.run(close_after_first_event())

            session.expire_all()
            detail = ConversationService(session).get_detail(user.id, conversation_id)
            assert detail.messages[0].status == "completed"
            assert detail.messages[1].status == "stopped"
            assert detail.messages[1].content == "已生成部分"
            assert detail.messages[1].sources == []
            assert generation_lock.acquired == 1
            assert generation_lock.released == 1
            assert idempotency.abandoned == 1
    finally:
        engine.dispose()


def test_active_stop_marks_stopped_and_releases_lock_before_next_request(
    tmp_path,
) -> None:
    engine, factory, _, user = build_test_database(tmp_path)
    try:
        with factory() as session:
            conversation = Conversation(user_id=user.id, title="主动停止")
            session.add(conversation)
            session.commit()
            generation_lock = AllowingGenerationLock()
            idempotency = AllowingIdempotency()
            cancellation = StreamCancellationService()
            generator = ConversationChatService(
                session,
                StoppableStreamRagService(),
                generation_lock,
                idempotency,
                cancellation,
            ).stream(
                user.id,
                conversation.id,
                "主动停止测试",
                2,
                "active-stop-request",
                "active-stop-key",
            )

            async def stop_after_first_event() -> None:
                first_event = await anext(generator)
                assert first_event["data"]["content"] == "已生成部分"
                assert cancellation.request_stop(
                    user.id, conversation.id, "active-stop-key"
                )
                stopped_event = await anext(generator)
                assert stopped_event["event"] == "stopped"
                assert stopped_event["data"]["message"] == "已停止生成。"
                with pytest.raises(StopAsyncIteration):
                    await anext(generator)

            asyncio.run(stop_after_first_event())

            session.expire_all()
            detail = ConversationService(session).get_detail(user.id, conversation.id)
            assert detail.messages[1].status == "stopped"
            assert detail.messages[1].content == "已生成部分"
            assert generation_lock.released == 1
            assert idempotency.abandoned == 1
            assert not cancellation.request_stop(
                user.id, conversation.id, "active-stop-key"
            )
    finally:
        engine.dispose()


def test_active_stop_cancels_a_model_stream_while_next_chunk_is_blocked(
    tmp_path,
) -> None:
    engine, factory, _, user = build_test_database(tmp_path)
    try:
        with factory() as session:
            conversation = Conversation(user_id=user.id, title="阻塞中停止")
            session.add(conversation)
            session.commit()
            generation_lock = AllowingGenerationLock()
            idempotency = AllowingIdempotency()
            cancellation = StreamCancellationService()
            rag = BlockingAsyncStreamRagService()
            generator = ConversationChatService(
                session,
                rag,
                generation_lock,
                idempotency,
                cancellation,
            ).stream(
                user.id,
                conversation.id,
                "请生成很长的回答",
                2,
                "blocked-stop-request",
                "blocked-stop-key",
            )

            async def stop_blocked_stream() -> float:
                first_event = await anext(generator)
                assert first_event["data"]["content"] == "已生成部分"
                stopped_event_task = asyncio.create_task(anext(generator))
                await asyncio.wait_for(rag.blocked.wait(), timeout=0.5)
                started = perf_counter()
                assert cancellation.request_stop(
                    user.id, conversation.id, "blocked-stop-key"
                )
                stopped_event = await stopped_event_task
                assert stopped_event["event"] == "stopped"
                return perf_counter() - started

            elapsed = asyncio.run(stop_blocked_stream())

            assert elapsed < 0.5
            assert rag.cancelled is True
            assert generation_lock.released == 1
            assert idempotency.abandoned == 1
    finally:
        engine.dispose()


def test_stop_endpoint_targets_current_user_and_request_key(tmp_path) -> None:
    engine, _, override_session, user = build_test_database(tmp_path)
    cancellation = StreamCancellationService()
    cancellation.register(user.id, "conversation-safe", "stop-key")
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_stream_cancellation_service] = lambda: cancellation
    try:
        with TestClient(app) as client:
            stopped = client.post(
                "/api/v1/conversations/conversation-safe/chat/stop",
                headers={**auth_headers(user.id), "Idempotency-Key": "stop-key"},
            )
            missing = client.post(
                "/api/v1/conversations/conversation-safe/chat/stop",
                headers={**auth_headers(user.id), "Idempotency-Key": "other-key"},
            )

        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopping"
        assert missing.status_code == 200
        assert missing.json()["status"] == "idle"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_other_user_cannot_use_normal_or_stream_chat_for_owned_conversation(
    tmp_path,
) -> None:
    engine, factory, override_session, owner = build_test_database(tmp_path)
    other_user = create_test_user(factory, "stream-other")
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_rag_service] = lambda: NeverCalledRagService()
    app.dependency_overrides[get_generation_lock_service] = AllowingGenerationLock
    app.dependency_overrides[get_idempotency_service] = AllowingIdempotency
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "仅所有者可用"},
                headers=auth_headers(owner.id),
            ).json()["id"]
            other_headers = auth_headers(other_user.id)

            normal = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "越权普通问答", "top_k": 2},
                headers={**other_headers, "Idempotency-Key": "other-normal"},
            )
            stream = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "越权流式问答", "top_k": 2},
                headers={**other_headers, "Idempotency-Key": "other-stream"},
            )

            for response in (normal, stream):
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"

            owner_detail = client.get(
                f"/api/v1/conversations/{conversation_id}",
                headers=auth_headers(owner.id),
            ).json()
            assert owner_detail["message_count"] == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            ConversationGenerationInProgressError(),
            409,
            "CONVERSATION_GENERATION_IN_PROGRESS",
        ),
        (GenerationLockUnavailableError(), 503, "GENERATION_LOCK_UNAVAILABLE"),
    ],
)
def test_stream_lock_rejection_happens_before_sse_and_message_creation(
    tmp_path, error, status_code, code
) -> None:
    engine, _, override_session, user = build_test_database(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: NeverCalledRagService()
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_generation_lock_service] = (
        lambda: RejectingGenerationLock(error)
    )
    app.dependency_overrides[get_idempotency_service] = AllowingIdempotency
    try:
        with TestClient(app) as client:
            headers = auth_headers(user.id)
            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "新对话"},
                headers=headers,
            ).json()["id"]

            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "不应开始流", "top_k": 2},
                headers={**headers, "Idempotency-Key": "stream-lock-rejected"},
            )

            assert response.status_code == status_code
            assert response.headers["content-type"].startswith("application/json")
            assert response.json()["error"]["code"] == code
            assert response.json()["request_id"]
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            ).json()
            assert detail["message_count"] == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
