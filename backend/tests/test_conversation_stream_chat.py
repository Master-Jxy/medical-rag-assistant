"""带会话流式问答的 completed、failed、stopped 状态测试。"""

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import RagServiceError
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation
from app.services.conversation_chat_service import ConversationChatService
from app.services.conversation_service import ConversationService
from app.services.rag_service import get_rag_service


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

    return engine, factory, override_session


def test_completed_stream_saves_answer_sources_and_done_ids(tmp_path) -> None:
    engine, _, override_session = build_test_database(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: SuccessfulStreamRagService()
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations", json={"title": "新对话"}
            ).json()["id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "流式成功测试", "top_k": 2},
            )
            assert response.status_code == 200
            assert response.text.count("event: token") == 2
            assert "event: sources" in response.text
            assert "event: done" in response.text
            assert "assistant_message_id" in response.text

            detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
            assistant = detail["messages"][1]
            assert assistant["status"] == "completed"
            assert assistant["content"] == "流式回答"
            assert assistant["sources"][0]["file_name"] == "指南.pdf"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_failed_stream_saves_partial_content_without_sources(tmp_path) -> None:
    engine, _, override_session = build_test_database(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: FailingStreamRagService()
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations", json={"title": "新对话"}
            ).json()["id"]
            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat/stream",
                json={"question": "流式失败测试", "top_k": 2},
            )
            assert "event: error" in response.text
            assert "测试流中错误" in response.text

            detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
            assistant = detail["messages"][1]
            assert assistant["status"] == "failed"
            assert assistant["content"] == "部分回答"
            assert assistant["sources"] == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_closing_stream_marks_assistant_stopped_and_keeps_partial_content(tmp_path) -> None:
    engine, factory, _ = build_test_database(tmp_path)
    try:
        with factory() as session:
            conversation = Conversation(title="新对话")
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id

            generator = ConversationChatService(
                session,
                StoppableStreamRagService(),
            ).stream(
                conversation_id,
                "主动停止测试",
                2,
                "stopped-request-id",
            )
            first_event = next(generator)
            assert first_event["data"]["content"] == "已生成部分"
            generator.close()

            session.expire_all()
            detail = ConversationService(session).get_detail(conversation_id)
            assert detail.messages[0].status == "completed"
            assert detail.messages[1].status == "stopped"
            assert detail.messages[1].content == "已生成部分"
            assert detail.messages[1].sources == []
    finally:
        engine.dispose()
