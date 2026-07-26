"""任务12.2：滚动摘要与用户可控记忆。"""

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import Conversation, Message, User
from app.modules.memory.schemas import UserMemoryWrite
from app.modules.memory.service import ConversationMemoryService, MemoryNotFoundError, UserMemoryService


def test_rolling_summary_keeps_older_messages_outside_recent_three_rounds() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="owner", email="owner@example.com", password_hash="hash"))
        conversation = Conversation(id="conversation-1", user_id="owner", title="长会话")
        conversation.messages = [
            Message(sequence=i, role="user" if i % 2 else "assistant", content=f"消息{i}")
            for i in range(1, 11)
        ]
        session.add(conversation); session.commit()
        service = ConversationMemoryService(session)
        prefixes = service.context_prefixes("owner", "conversation-1")
        assert prefixes[0][0] == "assistant"
        assert "消息1" in prefixes[0][1]
        assert "消息4" in prefixes[0][1]
        assert "消息5" not in prefixes[0][1]
        prefixes_again = service.context_prefixes("owner", "conversation-1")
        assert prefixes_again == prefixes
    engine.dispose()


def test_long_term_memory_is_default_off_and_user_controls_crud() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([
            User(id="owner", email="owner@example.com", password_hash="hash"),
            User(id="other", email="other@example.com", password_hash="hash"),
        ]); session.commit()
        service = UserMemoryService(session)
        assert service.get_setting("owner").enabled is False
        created = service.create("owner", UserMemoryWrite(label="偏好", content="回答尽量简洁"))
        assert service.list("owner").items[0].content == "回答尽量简洁"
        assert service.list("other").items == []
        service.update_setting("owner", True)
        assert service.get_setting("owner").enabled is True
        updated = service.update("owner", created.id, UserMemoryWrite(label="表达偏好", content="使用中文"))
        assert updated.content == "使用中文"
        service.delete("owner", created.id)
        assert service.list("owner").items == []
    engine.dispose()
