"""带会话普通问答测试：假 RAG + 临时数据库，不调用真实模型。"""

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import RagServiceError
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.schemas.chat import SourceItem
from app.modules.auth.tokens import get_token_service
from app.services.rag_service import get_rag_service
from app.services.generation_lock_service import (
    ConversationGenerationInProgressError,
    GenerationLockLease,
    GenerationLockUnavailableError,
    get_generation_lock_service,
)
from app.services.idempotency_service import get_idempotency_service
from tests.idempotency_helpers import AllowingIdempotency
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


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


class AllowingGenerationLock:
    def __init__(self) -> None:
        self.released = 0

    def acquire(self, user_id: str, conversation_id: str) -> GenerationLockLease:
        return GenerationLockLease("test-lock", "test-owner")

    def release(self, lease: GenerationLockLease) -> None:
        self.released += 1


class RejectingGenerationLock:
    def __init__(self, error) -> None:
        self.error = error

    def acquire(self, user_id: str, conversation_id: str):
        raise self.error


class NeverCalledRagService:
    def ask(self, question: str, top_k: int, history=None):
        raise AssertionError("锁拒绝后不应调用 RAG")


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

    user = create_test_user(factory, "chat-owner")
    return engine, override_session, auth_headers(user.id)


def test_conversation_chat_saves_completed_answer_and_sources(tmp_path) -> None:
    engine, override_session, headers = build_test_dependencies(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: SuccessfulRagService()
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    generation_lock = AllowingGenerationLock()
    idempotency = AllowingIdempotency()
    app.dependency_overrides[get_generation_lock_service] = lambda: generation_lock
    app.dependency_overrides[get_idempotency_service] = lambda: idempotency
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/conversations", json={"title": "新对话"}, headers=headers
            )
            conversation_id = created.json()["id"]

            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "高血压有哪些常见症状？", "top_k": 3},
                headers={**headers, "Idempotency-Key": "normal-success"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["conversation_id"] == conversation_id
            assert body["answer"].startswith("根据知识库资料")
            assert body["sources"][0]["file_name"] == "指南.pdf"
            assert body["user_message_id"]
            assert body["assistant_message_id"]

            detail = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            ).json()
            assert detail["title"] == "高血压有哪些常见症状？"
            assert detail["message_count"] == 2
            assert [message["status"] for message in detail["messages"]] == [
                "completed",
                "completed",
            ]
            assert detail["messages"][1]["request_id"] == body["request_id"]
            assert detail["messages"][1]["sources"][0]["page"] == 12
            assert generation_lock.released == 1
            assert idempotency.completed == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_conversation_chat_keeps_failed_assistant_message(tmp_path) -> None:
    engine, override_session, headers = build_test_dependencies(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: FailingRagService()
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    generation_lock = AllowingGenerationLock()
    idempotency = AllowingIdempotency()
    app.dependency_overrides[get_generation_lock_service] = lambda: generation_lock
    app.dependency_overrides[get_idempotency_service] = lambda: idempotency
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/conversations", json={"title": "新对话"}, headers=headers
            )
            conversation_id = created.json()["id"]

            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "模型失败测试", "top_k": 2},
                headers={**headers, "Idempotency-Key": "normal-failure"},
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "RAG_SERVICE_ERROR"

            detail = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            ).json()
            assert detail["message_count"] == 2
            assert detail["messages"][0]["status"] == "completed"
            assert detail["messages"][1]["status"] == "failed"
            assert detail["messages"][1]["request_id"]
            assert detail["messages"][1]["sources"] == []
            assert generation_lock.released == 1
            assert idempotency.abandoned == 1
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
def test_generation_lock_rejection_is_json_and_creates_no_messages(
    tmp_path, error, status_code, code
) -> None:
    engine, override_session, headers = build_test_dependencies(tmp_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_rag_service] = lambda: NeverCalledRagService()
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.dependency_overrides[get_generation_lock_service] = (
        lambda: RejectingGenerationLock(error)
    )
    idempotency = AllowingIdempotency()
    app.dependency_overrides[get_idempotency_service] = lambda: idempotency
    try:
        with TestClient(app) as client:
            conversation_id = client.post(
                "/api/v1/conversations", json={"title": "新对话"}, headers=headers
            ).json()["id"]

            response = client.post(
                f"/api/v1/conversations/{conversation_id}/chat",
                json={"question": "不应生成", "top_k": 2},
                headers={**headers, "Idempotency-Key": "lock-rejected"},
            )

            assert response.status_code == status_code
            assert response.json()["error"]["code"] == code
            assert response.json()["request_id"]
            detail = client.get(
                f"/api/v1/conversations/{conversation_id}", headers=headers
            ).json()
            assert detail["message_count"] == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
