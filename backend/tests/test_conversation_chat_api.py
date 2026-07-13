"""带会话普通问答测试：假 RAG + 临时数据库，不调用真实模型。"""

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import RagServiceError
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.schemas.chat import SourceItem
from app.services.rag_service import get_rag_service


class SuccessfulRagService:
    def ask(self, question: str, top_k: int, history=None):
        assert question == "高血压有哪些常见症状？"
        assert top_k == 3
        assert history == []
        return (
            "根据知识库资料，高血压可能没有明显症状。",
            [SourceItem(file_name="指南.pdf", page=12, content="引用原文")],
        )


class FailingRagService:
    def ask(self, question: str, top_k: int, history=None):
        raise RagServiceError("测试模型故障")


def build_test_dependencies(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'conversation-chat.db'}")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    return engine, override_session


def test_conversation_chat_saves_completed_answer_and_sources(tmp_path) -> None:
    engine, override_session = build_test_dependencies(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: SuccessfulRagService()
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/conversations", json={"title": "新对话"})
            conversation_id = created.json()["id"]

            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "高血压有哪些常见症状？", "top_k": 3},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["conversation_id"] == conversation_id
            assert body["answer"].startswith("根据知识库资料")
            assert body["sources"][0]["file_name"] == "指南.pdf"
            assert body["user_message_id"]
            assert body["assistant_message_id"]

            detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
            assert detail["title"] == "高血压有哪些常见症状？"
            assert detail["message_count"] == 2
            assert [message["status"] for message in detail["messages"]] == [
                "completed",
                "completed",
            ]
            assert detail["messages"][1]["request_id"] == body["request_id"]
            assert detail["messages"][1]["sources"][0]["page"] == 12
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_conversation_chat_keeps_failed_assistant_message(tmp_path) -> None:
    engine, override_session = build_test_dependencies(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: FailingRagService()
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/conversations", json={"title": "新对话"})
            conversation_id = created.json()["id"]

            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "模型失败测试", "top_k": 2},
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "RAG_SERVICE_ERROR"

            detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
            assert detail["message_count"] == 2
            assert detail["messages"][0]["status"] == "completed"
            assert detail["messages"][1]["status"] == "failed"
            assert detail["messages"][1]["request_id"]
            assert detail["messages"][1]["sources"] == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
