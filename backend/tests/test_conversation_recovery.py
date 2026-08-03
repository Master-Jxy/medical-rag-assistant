"""RAG 会话进程中断恢复测试：只使用临时 SQLite，不调用真实模型。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation, Message, User
from app.modules.auth.tokens import get_token_service
from app.services.conversation_recovery import (
    RAG_INTERRUPTED_MESSAGE,
    ConversationRecoveryService,
)
from app.services.conversation_service import ConversationService
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def _create_schema_and_user(engine, user_id: str) -> User:
    Base.metadata.create_all(engine)
    return User(
        id=user_id,
        email=f"{user_id}@example.com",
        password_hash="not-used",
    )


def test_only_stale_pending_assistant_messages_are_recovered() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = _create_schema_and_user(engine, "recovery-owner")
            conversation = Conversation(user_id=user.id, title="中断恢复")
            old = datetime.now(timezone.utc) - timedelta(seconds=901)
            fresh = datetime.now(timezone.utc) - timedelta(seconds=10)
            conversation.messages.extend(
                [
                    Message(
                        sequence=1,
                        role="assistant",
                        content="部分旧输出",
                        status="pending",
                        created_at=old,
                    ),
                    Message(
                        sequence=2,
                        role="assistant",
                        content="仍在生成",
                        status="pending",
                        created_at=fresh,
                    ),
                    Message(
                        sequence=3,
                        role="user",
                        content="用户问题",
                        status="completed",
                        created_at=old,
                    ),
                    Message(
                        sequence=4,
                        role="assistant",
                        content="已经完成",
                        status="completed",
                        created_at=old,
                    ),
                    Message(
                        sequence=5,
                        role="assistant",
                        content="已停止",
                        status="stopped",
                        created_at=old,
                    ),
                ]
            )
            session.add_all([user, conversation])
            session.commit()
            original_updated_at = conversation.updated_at

            recovered = ConversationRecoveryService(
                session, recovery_age_seconds=900
            ).recover_interrupted()

            assert recovered == 1
            assert conversation.updated_at > original_updated_at
            assert conversation.messages[0].status == "failed"
            assert conversation.messages[0].content == RAG_INTERRUPTED_MESSAGE
            assert conversation.messages[1].status == "pending"
            assert conversation.messages[1].content == "仍在生成"
            assert conversation.messages[2].status == "completed"
            assert conversation.messages[3].status == "completed"
            assert conversation.messages[4].status == "stopped"
    finally:
        engine.dispose()


def test_recovered_conversation_is_idle_and_unread() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = _create_schema_and_user(engine, "recovery-summary")
            conversation = Conversation(user_id=user.id, title="摘要状态")
            conversation.messages.extend(
                [
                    Message(sequence=1, role="user", content="问题"),
                    Message(
                        sequence=2,
                        role="assistant",
                        content="",
                        status="pending",
                        created_at=datetime.now(timezone.utc)
                        - timedelta(seconds=901),
                    ),
                ]
            )
            session.add_all([user, conversation])
            session.commit()

            ConversationRecoveryService(session).recover_interrupted()
            summary = ConversationService(session).list(
                user.id, limit=20, offset=0
            ).conversations[0]

            assert summary.run_status == "idle"
            assert summary.last_message_status == "failed"
            assert summary.has_unread is True
    finally:
        engine.dispose()


def test_recovery_handles_multiple_users_without_exposing_data() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    try:
        with Session(engine, expire_on_commit=False) as session:
            user_a = _create_schema_and_user(engine, "recovery-a")
            user_b = User(
                id="recovery-b",
                email="recovery-b@example.com",
                password_hash="not-used",
            )
            conversation_a = Conversation(user_id=user_a.id, title="A")
            conversation_b = Conversation(user_id=user_b.id, title="B")
            old = datetime.now(timezone.utc) - timedelta(seconds=901)
            conversation_a.messages.append(
                Message(
                    sequence=1,
                    role="assistant",
                    content="A的残留",
                    status="pending",
                    created_at=old,
                )
            )
            conversation_b.messages.append(
                Message(
                    sequence=1,
                    role="assistant",
                    content="B的残留",
                    status="pending",
                    created_at=old,
                )
            )
            session.add_all([user_a, user_b, conversation_a, conversation_b])
            session.commit()

            assert ConversationRecoveryService(session).recover_interrupted() == 2
            assert conversation_a.messages[0].status == "failed"
            assert conversation_b.messages[0].status == "failed"
            assert conversation_a.messages[0].content == RAG_INTERRUPTED_MESSAGE
            assert conversation_b.messages[0].content == RAG_INTERRUPTED_MESSAGE
            assert ConversationService(session).list(
                user_a.id, limit=20, offset=0
            ).total == 1
            assert ConversationService(session).list(
                user_b.id, limit=20, offset=0
            ).total == 1
    finally:
        engine.dispose()


def test_recovery_age_must_outlive_generation_lock_cleanup_window() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            generation_lock_ttl_seconds=600,
            generation_lock_cleanup_grace_seconds=30,
            rag_pending_recovery_age_seconds=630,
        )


def test_conversations_api_runs_recovery_before_listing(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'api-recovery.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "api-recovery")
    with factory() as session:
        conversation = Conversation(user_id=user.id, title="接口恢复")
        conversation.messages.append(
            Message(
                sequence=1,
                role="assistant",
                content="残留输出",
                status="pending",
                created_at=datetime.now(timezone.utc) - timedelta(seconds=901),
            )
        )
        session.add(conversation)
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    app.state.conversation_recovery_complete = False
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/conversations",
                headers=auth_headers(user.id),
            )
            assert response.status_code == 200
            summary = response.json()["conversations"][0]
            assert summary["run_status"] == "idle"
            assert summary["last_message_status"] == "failed"
    finally:
        app.dependency_overrides.clear()
        app.state.conversation_recovery_complete = False
        engine.dispose()
