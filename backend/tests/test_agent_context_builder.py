"""任务13.2：Agent会话服务、上下文预算、摘要与显式记忆。"""

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.agent.context_builder import AgentContextBuilder
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_repository import AgentThreadRepository
from app.modules.agent.thread_service import AgentThreadService
from app.modules.memory.agent_context import SqlAlchemyAgentMemoryContext
from app.modules.memory.models import UserMemory, UserMemorySetting


class FakeMemory:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def load_enabled_memories(self, user_id: str, *, limit: int) -> list[str]:
        assert user_id == "owner"
        return self.values[:limit]


def create_user(session: Session, user_id: str) -> None:
    session.add(
        User(
            id=user_id,
            email=f"{user_id}@example.com",
            password_hash="hash",
        )
    )
    session.flush()


def test_context_prioritizes_current_explicit_recent_summary_and_memory() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        threads = AgentThreadRepository(session)
        thread = threads.create_thread(user_id="owner", title="连续任务")
        referenced = threads.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="assistant",
            content="上一轮报告结论",
        )
        recent = threads.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="user",
            content="上一轮问题",
        )
        thread.summary = "更早目标：学习患者安全"
        current = threads.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="user",
            content="根据刚才结果继续整理",
            metadata={
                "referenced_message_ids": [referenced.id],
                "source_ids": ["doc-1"],
            },
        )
        bundle = AgentContextBuilder(
            threads,
            AgentRepository(session),
            FakeMemory(["偏好：使用表格"]),
            max_tokens=1000,
        ).build(
            user_id="owner",
            thread_id=thread.id,
            current_message=current,
        )

        assert bundle.rendered.startswith(
            "[当前任务]\n根据刚才结果继续整理"
        )
        assert "上一轮报告结论" in bundle.rendered
        assert "上一轮问题" in bundle.rendered
        assert "更早目标：学习患者安全" in bundle.rendered
        assert "偏好：使用表格" in bundle.rendered
        assert "doc-1" in bundle.rendered
        assert bundle.assistant_mode == "general"
        assert bundle.resolved_references.source_ids == ("doc-1",)
        assert bundle.resolved_references.message_ids == (referenced.id,)
        assert bundle.rendered.index("[用户显式记忆]") < bundle.rendered.index(
            "[最近消息]"
        )
        assert dict(bundle.section_tokens)["当前任务"] > 0
        assert referenced.id in bundle.included_message_ids
        assert recent.id in bundle.included_message_ids
        assert bundle.included_memory_count == 1
    engine.dispose()


def test_context_truncates_low_priority_memory_but_keeps_required_sections() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        threads = AgentThreadRepository(session)
        thread = threads.create_thread(user_id="owner")
        current = threads.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="user",
            content="当前任务必须保留",
            metadata={"source_ids": ["doc-required"]},
        )
        bundle = AgentContextBuilder(
            threads,
            AgentRepository(session),
            FakeMemory(["低优先级记忆" * 200]),
            max_tokens=80,
        ).build(
            user_id="owner",
            thread_id=thread.id,
            current_message=current,
        )

        assert "当前任务必须保留" in bundle.rendered
        assert "系统安全约束" in bundle.rendered
        assert "doc-required" in bundle.rendered
        assert "低优先级记忆" not in bundle.rendered
        assert bundle.truncated is True
    engine.dispose()


def test_thread_service_refreshes_only_messages_before_recent_window() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        threads = AgentThreadRepository(session)
        service = AgentThreadService(session, recent_message_count=2)
        thread = threads.create_thread(user_id="owner")
        messages = [
            threads.create_message(
                user_id="owner",
                thread_id=thread.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"消息{index}",
            )
            for index in range(6)
        ]
        session.commit()

        service.refresh_summary("owner", thread.id)
        session.refresh(thread)
        assert "消息0" in (thread.summary or "")
        assert "消息3" in (thread.summary or "")
        assert "消息4" not in (thread.summary or "")
        assert thread.summary_until_message_id == messages[3].id

        service.refresh_summary("owner", thread.id)
        session.refresh(thread)
        assert (thread.summary or "").count("消息0") == 1
    engine.dispose()


def test_sqlalchemy_memory_context_reads_only_explicitly_enabled_user_memory() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        create_user(session, "owner")
        session.add(
            UserMemory(
                user_id="owner",
                label="输出偏好",
                content="使用表格",
            )
        )
        session.add(UserMemorySetting(user_id="owner", enabled=False))
        session.commit()
        adapter = SqlAlchemyAgentMemoryContext(session)
        assert adapter.load_enabled_memories("owner", limit=20) == []

        session.get(UserMemorySetting, "owner").enabled = True
        session.commit()
        assert adapter.load_enabled_memories("owner", limit=20) == [
            "输出偏好：使用表格"
        ]
    engine.dispose()
