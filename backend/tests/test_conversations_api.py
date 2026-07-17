"""会话 CRUD 接口测试：使用临时 SQLite，不接触真实 MySQL。"""

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation, Message, MessageSource
from app.modules.auth.tokens import get_token_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def test_conversation_crud_with_messages_and_sources(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'conversations.db'}")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(test_session_factory, "crud-owner")
    headers = auth_headers(user.id)

    def override_session():
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/v1/conversations",
                json={"title": " 高血压资料查询 "},
                headers=headers,
            )
            assert create_response.status_code == 201
            conversation_id = create_response.json()["id"]
            assert create_response.json()["title"] == "高血压资料查询"
            assert create_response.json()["message_count"] == 0

            with test_session_factory() as session:
                conversation = session.get(Conversation, conversation_id)
                assert conversation.user_id == user.id
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

            list_response = client.get(
                "/api/v1/conversations?limit=10&offset=0", headers=headers
            )
            assert list_response.status_code == 200
            assert list_response.json()["total"] == 1
            assert list_response.json()["conversations"][0]["message_count"] == 2

            detail_response = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            )
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
            assert detail["messages"][1]["sources"][0]["file_name"] == "指南.pdf"

            update_response = client.patch(
                f"/api/v1/conversations/{conversation_id}",
                json={"title": "新的会话标题"},
                headers=headers,
            )
            assert update_response.status_code == 200
            assert update_response.json()["title"] == "新的会话标题"
            assert update_response.json()["message_count"] == 2

            delete_response = client.delete(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            )
            assert delete_response.status_code == 200
            assert delete_response.json()["conversation_id"] == conversation_id

            missing_response = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            )
            assert missing_response.status_code == 404
            assert missing_response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"

            final_list = client.get("/api/v1/conversations", headers=headers)
            assert final_list.json()["total"] == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_conversation_title_and_pagination_are_validated(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'validation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "validation")

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    try:
        with TestClient(app) as client:
            headers = auth_headers(user.id)
            blank_title = client.post(
                "/api/v1/conversations", json={"title": "   "}, headers=headers
            )
            invalid_limit = client.get(
                "/api/v1/conversations?limit=101", headers=headers
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert blank_title.status_code == 422
    assert invalid_limit.status_code == 422


def test_two_users_cannot_list_read_update_or_delete_each_others_conversations(
    tmp_path,
) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'isolation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user_a = create_test_user(factory, "isolation-a")
    user_b = create_test_user(factory, "isolation-b")

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    try:
        with TestClient(app) as client:
            headers_a = auth_headers(user_a.id)
            headers_b = auth_headers(user_b.id)
            missing_token = client.get("/api/v1/conversations")
            assert missing_token.status_code == 401
            assert missing_token.json()["error"]["code"] == "INVALID_AUTH_TOKEN"

            conversation_id = client.post(
                "/api/v1/conversations",
                json={"title": "A的私有会话"},
                headers=headers_a,
            ).json()["id"]

            assert client.get("/api/v1/conversations", headers=headers_a).json()["total"] == 1
            assert client.get("/api/v1/conversations", headers=headers_b).json()["total"] == 0

            cross_user_responses = [
                client.get(f"/api/v1/conversations/{conversation_id}", headers=headers_b),
                client.patch(
                    f"/api/v1/conversations/{conversation_id}",
                    json={"title": "B不能改"},
                    headers=headers_b,
                ),
                client.delete(
                    f"/api/v1/conversations/{conversation_id}", headers=headers_b
                ),
            ]
            for response in cross_user_responses:
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"

            owner_detail = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers_a
            )
            assert owner_detail.status_code == 200
            assert owner_detail.json()["title"] == "A的私有会话"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
