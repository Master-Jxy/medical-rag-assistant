"""会话 CRUD 接口测试：使用临时 SQLite，不接触真实 MySQL。"""

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation, Message, MessageSource


def test_conversation_crud_with_messages_and_sources(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'conversations.db'}")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/v1/conversations",
                json={"title": " 高血压资料查询 "},
            )
            assert create_response.status_code == 201
            conversation_id = create_response.json()["id"]
            assert create_response.json()["title"] == "高血压资料查询"
            assert create_response.json()["message_count"] == 0

            with test_session_factory() as session:
                conversation = session.get(Conversation, conversation_id)
                conversation.messages.extend(
                    [
                        Message(sequence=1, role="user", content="有哪些常见症状？"),
                        Message(
                            sequence=2,
                            role="assistant",
                            content="根据资料……",
                            request_id="request-1",
                            sources=[
                                MessageSource(
                                    position=1,
                                    file_name="指南.pdf",
                                    page=12,
                                    content="引用原文",
                                )
                            ],
                        ),
                    ]
                )
                session.commit()

            list_response = client.get("/api/v1/conversations?limit=10&offset=0")
            assert list_response.status_code == 200
            assert list_response.json()["total"] == 1
            assert list_response.json()["conversations"][0]["message_count"] == 2

            detail_response = client.get(f"/api/v1/conversations/{conversation_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
            assert detail["messages"][1]["sources"][0]["file_name"] == "指南.pdf"

            update_response = client.patch(
                f"/api/v1/conversations/{conversation_id}",
                json={"title": "新的会话标题"},
            )
            assert update_response.status_code == 200
            assert update_response.json()["title"] == "新的会话标题"
            assert update_response.json()["message_count"] == 2

            delete_response = client.delete(f"/api/v1/conversations/{conversation_id}")
            assert delete_response.status_code == 200
            assert delete_response.json()["conversation_id"] == conversation_id

            missing_response = client.get(f"/api/v1/conversations/{conversation_id}")
            assert missing_response.status_code == 404
            assert missing_response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"

            final_list = client.get("/api/v1/conversations")
            assert final_list.json()["total"] == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_conversation_title_and_pagination_are_validated() -> None:
    with TestClient(app) as client:
        blank_title = client.post("/api/v1/conversations", json={"title": "   "})
        invalid_limit = client.get("/api/v1/conversations?limit=101")

    assert blank_title.status_code == 422
    assert invalid_limit.status_code == 422
