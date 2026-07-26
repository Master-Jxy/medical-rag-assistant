from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.agent.models import AgentRun
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_repository import AgentThreadRepository
from scripts.cleanup_legacy_agent_runs import (
    CONFIRM_PHRASE,
    cleanup_legacy_runs,
)


def test_legacy_cleanup_is_dry_run_by_default_and_preserves_threaded_runs():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="owner", email="owner@example.com", password_hash="x"))
        session.flush()
        runs = AgentRepository(session)
        threads = AgentThreadRepository(session)
        legacy = runs.create_run(
            user_id="owner",
            task="旧任务",
            policy=AgentPolicy(),
        )
        thread = threads.create_thread(user_id="owner")
        trigger = threads.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="user",
            content="新任务",
        )
        threaded = runs.create_run(
            user_id="owner",
            task="新任务",
            policy=AgentPolicy(),
            thread_id=thread.id,
            trigger_message_id=trigger.id,
        )
        session.commit()

        preview = cleanup_legacy_runs(session)
        assert preview.runs == 1
        assert preview.deleted is False
        assert session.get(AgentRun, legacy.id) is not None

        result = cleanup_legacy_runs(
            session,
            confirmation=CONFIRM_PHRASE,
        )
        assert result.deleted is True
        assert session.get(AgentRun, legacy.id) is None
        assert session.get(AgentRun, threaded.id) is not None
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 1
    engine.dispose()
