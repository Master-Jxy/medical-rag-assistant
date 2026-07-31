from datetime import datetime, timedelta, timezone
import hashlib

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.memory.context_provider import SqlAlchemyMemoryContextProvider
from app.modules.memory.contracts import FakeMemoryExtractionModel
from app.modules.memory.extraction_service import MemoryExtractionService
from app.modules.memory.models import (
    MemoryExtractionRun,
    UserMemory,
    UserMemoryRevision,
    UserMemorySource,
    UserMemorySetting,
)
from app.modules.usage.contracts import ModelUsage
from app.modules.usage.models import ModelUsageRecord
from app.modules.usage.service import ModelUsageRecorder


def test_sensitive_extraction_stays_candidate_and_schedule_is_idempotent():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(UserMemorySetting(user_id="u", enabled=True, auto_extract_enabled=True))
        session.commit()
        model = FakeMemoryExtractionModel({"candidates": [{
            "category": "health_context", "label": "健康背景", "content": "用户明确说有高血压",
            "confidence": 0.99, "sensitive": True, "source_message_ids": ["m1"],
        }]})
        service = MemoryExtractionService(session, model, FakeSourceReader())
        first = service.schedule("u", "rag", "t", 2)
        second = service.schedule("u", "rag", "t", 2)
        assert first.id == second.id
        service.execute(first.id, [{"role": "user", "content": "有高血压"}])
        memory = session.query(UserMemory).one()
        assert memory.status == "candidate"
        assert model.calls == 1
    engine.dispose()


def test_context_provider_is_relevant_bounded_and_user_isolated():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            User(id="a", email="a@example.com", password_hash="x"),
            User(id="b", email="b@example.com", password_hash="x"),
            UserMemorySetting(user_id="a", enabled=True),
            UserMemorySetting(user_id="b", enabled=True),
            UserMemory(user_id="a", label="目标", content="准备Python后端面试", category="goal"),
            UserMemory(user_id="a", label="偏好", content="喜欢简洁回答", category="preference"),
            UserMemory(user_id="b", label="目标", content="准备Java面试", category="goal"),
        ])
        session.commit()
        context = SqlAlchemyMemoryContextProvider(session, rag_max_items=1).search(
            "a", "Python面试怎么准备", surface="rag")
        assert [item.content for item in context.items] == ["准备Python后端面试"]
        assert all("Java" not in item.content for item in context.items)
    engine.dispose()


class FailingExtractionModel:
    def __init__(self):
        self.calls = 0

    def extract(self, messages):
        del messages
        self.calls += 1
        raise RuntimeError("fake model failure")


class FakeSourceReader:
    def read_completed(self, **kwargs):
        del kwargs
        return [{"role": "user", "content": "hello"}]

    def owns_messages(self, **kwargs):
        del kwargs
        return True


class RestrictedSourceReader(FakeSourceReader):
    def __init__(self, owned_ids):
        self.owned_ids = set(owned_ids)

    def owns_messages(self, **kwargs):
        return set(kwargs["message_ids"]).issubset(self.owned_ids)


def test_failed_extraction_is_persisted_and_retried_only_once():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(UserMemorySetting(
            user_id="u", enabled=True, auto_extract_enabled=True
        ))
        session.commit()
        model = FailingExtractionModel()
        service = MemoryExtractionService(session, model, FakeSourceReader())
        run = service.schedule("u", "rag", "thread", 2)

        first = service.execute(run.id, [{"role": "user", "content": "hello"}])
        assert first.status == "failed"
        assert first.error_code == "MODEL_CALL_FAILED"
        assert first.attempt_count == 1

        service.recover_pending(limit=10)
        session.refresh(first)
        assert first.status == "failed"
        assert first.attempt_count == 2
        assert service.recover_pending(limit=10) == []
        assert model.calls == 2
    engine.dispose()


def test_extraction_deduplicates_conflicts_and_rejects_unowned_sources():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(UserMemorySetting(
            user_id="u", enabled=True, auto_extract_enabled=True
        ))
        original_content = "准备Python后端面试"
        original = UserMemory(
            user_id="u",
            label="目标",
            content=original_content,
            category="goal",
            status="active",
            normalized_hash=hashlib.sha256(
                original_content.lower().encode()
            ).hexdigest(),
        )
        session.add(original)
        session.commit()
        model = FakeMemoryExtractionModel({"candidates": [
            {
                "category": "goal",
                "label": "重复内容",
                "content": original_content,
                "confidence": 0.99,
                "sensitive": False,
                "source_message_ids": ["owned"],
            },
            {
                "category": "goal",
                "label": "目标",
                "content": "改为准备医疗AI后端面试",
                "confidence": 0.99,
                "sensitive": False,
                "source_message_ids": ["owned"],
            },
            {
                "category": "preference",
                "label": "越权来源",
                "content": "不属于当前用户的消息",
                "confidence": 0.99,
                "sensitive": False,
                "source_message_ids": ["other-user-message"],
            },
        ]})
        service = MemoryExtractionService(
            session,
            model,
            RestrictedSourceReader({"owned"}),
        )
        run = service.schedule("u", "rag", "thread", 2)
        completed = service.execute(run.id)

        memories = session.query(UserMemory).order_by(
            UserMemory.created_at
        ).all()
        assert completed.status == "completed"
        assert completed.candidate_count == 1
        assert len(memories) == 2
        candidate = next(row for row in memories if row.id != original.id)
        assert candidate.status == "candidate"
        assert candidate.supersedes_id == original.id
        assert session.query(UserMemoryRevision).filter_by(
            memory_id=candidate.id
        ).count() == 1
        sources = session.query(UserMemorySource).filter_by(
            memory_id=candidate.id
        ).all()
        assert [row.message_id for row in sources] == ["owned"]
    engine.dispose()


def test_recovery_does_not_take_over_a_fresh_running_job():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(UserMemorySetting(
            user_id="u", enabled=True, auto_extract_enabled=True
        ))
        session.add_all([
            MemoryExtractionRun(
                user_id="u",
                surface="rag",
                thread_id="fresh",
                through_sequence=2,
                status="running",
                started_at=datetime.now(timezone.utc),
            ),
            MemoryExtractionRun(
                user_id="u",
                surface="agent",
                thread_id="stale",
                through_sequence=2,
                status="running",
                started_at=datetime.now(timezone.utc) - timedelta(minutes=16),
            ),
        ])
        session.commit()
        model = FakeMemoryExtractionModel({"candidates": []})
        recovered = MemoryExtractionService(
            session, model, FakeSourceReader()
        ).recover_pending()
        assert [row.thread_id for row in recovered] == ["stale"]
        fresh = session.query(MemoryExtractionRun).filter_by(
            thread_id="fresh"
        ).one()
        assert fresh.status == "running"
        assert model.calls == 1
    engine.dispose()


def test_memory_extraction_usage_is_separate_and_not_quota_billable():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(UserMemorySetting(
            user_id="u", enabled=True, auto_extract_enabled=True
        ))
        session.commit()
        model = FakeMemoryExtractionModel(
            {"candidates": []},
            usage=ModelUsage.actual(30, 5),
        )
        service = MemoryExtractionService(
            session,
            model,
            FakeSourceReader(),
            usage_recorder=ModelUsageRecorder(session),
            model_name="fake-memory",
        )
        run = service.schedule("u", "rag", "thread", 2)
        service.execute(run.id)

        record = session.query(ModelUsageRecord).one()
        assert record.surface == "memory"
        assert record.usage_group_id == run.id
        assert record.total_tokens == 35
        assert record.quota_billable is False
    engine.dispose()
