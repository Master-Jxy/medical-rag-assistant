"""Alembic 测试：验证最新结构、旧会话清理、用户保留和可降级结构。"""

from datetime import datetime, timezone
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.models import Conversation, Message, MessageSource, User
from app.models import KnowledgeDocument
from app.modules.knowledge.migration import import_legacy_registry

BACKEND_DIR = Path(__file__).resolve().parents[1]


def build_alembic_config(database_url: str) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_empty_database_upgrades_to_owned_conversation_schema(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'empty.db'}"
    command.upgrade(build_alembic_config(database_url), "head")

    engine = build_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "alembic_version",
        "conversations",
        "messages",
        "message_sources",
        "users",
        "documents",
    } <= tables

    columns = {column["name"]: column for column in inspector.get_columns("conversations")}
    assert columns["user_id"]["nullable"] is False
    foreign_keys = inspector.get_foreign_keys("conversations")
    assert any(
        foreign_key["constrained_columns"] == ["user_id"]
        and foreign_key["referred_table"] == "users"
        for foreign_key in foreign_keys
    )
    index_names = {index["name"] for index in inspector.get_indexes("conversations")}
    assert "ix_conversations_user_updated_at" in index_names

    document_columns = {
        column["name"]: column for column in inspector.get_columns("documents")
    }
    assert document_columns["uploader_id"]["nullable"] is True
    assert document_columns["is_system"]["nullable"] is False
    assert any(
        foreign_key["constrained_columns"] == ["uploader_id"]
        and foreign_key["referred_table"] == "users"
        for foreign_key in inspector.get_foreign_keys("documents")
    )
    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["role"]["nullable"] is False


def test_upgrade_clears_unowned_conversations_but_preserves_users(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'existing.db'}"
    config = build_alembic_config(database_url)
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    command.upgrade(config, "0001_conversation")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES (:id, :title, :created_at, :updated_at)"
            ),
            {
                "id": "legacy-conversation",
                "title": "迁移前测试会话",
                "created_at": now,
                "updated_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, sequence, role, content, status, request_id, created_at) "
                "VALUES (:id, :conversation_id, 1, 'assistant', '迁移前消息', "
                "'completed', 'legacy-request', :created_at)"
            ),
            {
                "id": "legacy-message",
                "conversation_id": "legacy-conversation",
                "created_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO message_sources "
                "(message_id, position, file_name, page, content) "
                "VALUES ('legacy-message', 1, '旧资料.txt', NULL, '迁移前引用')"
            )
        )

    command.upgrade(config, "0002_users")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, display_name, password_hash, is_active, created_at, updated_at) "
                "VALUES ('preserved-user', 'preserved@example.com', NULL, 'hash', 1, :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(MessageSource)) == 0
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.get(User, "preserved-user") is not None
        assert session.get(User, "preserved-user").role == "user"

    command.downgrade(config, "0002_users")
    assert "user_id" not in {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM users WHERE id = 'preserved-user'")
        ) == 1


def test_legacy_json_import_creates_idempotent_system_documents(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'documents.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "head")
    registry_path = tmp_path / "documents.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "document_id": "legacy-document",
                    "file_name": "系统资料.txt",
                    "stored_name": "legacy-document.txt",
                    "file_hash": "a" * 64,
                    "file_size": 128,
                    "chunk_count": 2,
                    "chunk_ids": ["legacy-document:0", "legacy-document:1"],
                    "status": "ready",
                    "created_at": "2026-07-15T00:00:00+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    engine = build_engine(database_url)
    with Session(engine) as session:
        assert import_legacy_registry(session, registry_path) == 1
        assert import_legacy_registry(session, registry_path) == 0
        saved = session.get(KnowledgeDocument, "legacy-document")
        assert saved is not None
        assert saved.is_system is True
        assert saved.uploader_id is None
        assert saved.chunk_ids == ["legacy-document:0", "legacy-document:1"]

    command.downgrade(config, "0003_conversation_user")
    assert "documents" not in inspect(engine).get_table_names()
