"""会话模型测试：使用内存 SQLite，不需要本地 MySQL。"""

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.session import build_engine
from app.models import Conversation, Message, MessageSource


def build_test_engine():
    engine = build_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def test_conversation_contains_ordered_messages_and_sources() -> None:
    engine = build_test_engine()
    with Session(engine) as session:
        conversation = Conversation(title="高血压资料查询")
        conversation.messages.extend(
            [
                Message(sequence=1, role="user", content="高血压有哪些常见症状？"),
                Message(
                    sequence=2,
                    role="assistant",
                    content="根据知识库资料……",
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
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id

    with Session(engine) as session:
        saved = session.get(Conversation, conversation_id)
        assert saved is not None
        assert [message.role for message in saved.messages] == ["user", "assistant"]
        assert saved.messages[1].sources[0].file_name == "指南.pdf"
        assert saved.messages[1].sources[0].page == 12


def test_deleting_conversation_cascades_to_messages_and_sources() -> None:
    engine = build_test_engine()
    with Session(engine) as session:
        conversation = Conversation(
            messages=[
                Message(
                    sequence=1,
                    role="assistant",
                    content="测试回答",
                    sources=[
                        MessageSource(position=1, file_name="资料.txt", content="引用")
                    ],
                )
            ]
        )
        session.add(conversation)
        session.commit()
        session.delete(conversation)
        session.commit()

        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(MessageSource)) == 0


def test_database_rejects_invalid_message_role() -> None:
    engine = build_test_engine()
    with Session(engine) as session:
        conversation = Conversation()
        conversation.messages.append(Message(sequence=1, role="system", content="非法角色"))
        session.add(conversation)
        with pytest.raises(IntegrityError):
            session.commit()


def test_models_can_compile_to_mysql_ddl_without_connecting() -> None:
    statements = [
        str(CreateTable(table).compile(dialect=mysql.dialect()))
        for table in Base.metadata.sorted_tables
    ]

    assert any("CREATE TABLE conversations" in statement for statement in statements)
    assert any("CREATE TABLE messages" in statement for statement in statements)
    assert any("CREATE TABLE message_sources" in statement for statement in statements)
