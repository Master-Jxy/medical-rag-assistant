"""任务11.2：Agent持久化、用户隔离和状态机。"""

from sqlalchemy.orm import Session
import pytest

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.repository import (
    AgentRepository,
    AgentRunNotFoundError,
    AgentStateConflictError,
    UnsafeAgentPayloadError,
)


def create_user(session: Session, user_id: str) -> None:
    session.add(
        User(
            id=user_id,
            email=f"{user_id}@example.com",
            password_hash="hash",
        )
    )
    session.flush()


def test_agent_repository_isolates_runs_steps_and_artifacts_by_user() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        create_user(session, "other")
        repository = AgentRepository(session)
        run = repository.create_run(
            user_id="owner",
            task="整理患者安全资料",
            policy=AgentPolicy(),
            model_name="mock",
        )
        repository.start_run("owner", run.id)
        step = repository.append_step(
            user_id="owner",
            run_id=run.id,
            node_name="execute_tool",
            tool_name="mock_search",
            parameters={"query": "患者安全"},
        )
        repository.finish_step(
            user_id="owner",
            step_id=step.id,
            status="completed",
            result_summary="检索到1份资料",
            duration_ms=12,
        )
        artifact = repository.add_artifact(
            user_id="owner",
            run_id=run.id,
            artifact_type="learning_report",
            file_name="report.md",
            mime_type="text/markdown",
            content="# 报告",
            source_ids=["doc-1"],
        )
        repository.complete_run(
            "owner",
            run.id,
            final_result="整理完成",
            used_tokens=100,
            estimated_cost_cny=0.001,
        )
        session.commit()

        detail = repository.get_run("owner", run.id, include_details=True)
        assert detail.status == "completed"
        assert [item.id for item in detail.steps] == [step.id]
        assert [item.id for item in detail.artifacts] == [artifact.id]
        assert repository.list_runs("owner") == [detail]
        assert repository.list_runs("other") == []
        with pytest.raises(AgentRunNotFoundError):
            repository.get_run("other", run.id, include_details=True)
        with pytest.raises(AgentRunNotFoundError):
            repository.add_artifact(
                user_id="other",
                run_id=run.id,
                artifact_type="report",
                file_name="stolen.md",
                mime_type="text/markdown",
                content="blocked",
                source_ids=[],
            )
    engine.dispose()


def test_agent_state_transitions_step_limit_and_private_reasoning_are_rejected() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        repository = AgentRepository(session)
        run = repository.create_run(
            user_id="owner",
            task="固定两步",
            policy=AgentPolicy(max_steps=2),
        )
        with pytest.raises(AgentStateConflictError):
            repository.append_step(
                user_id="owner",
                run_id=run.id,
                node_name="execute_tool",
                tool_name=None,
                parameters={},
            )
        repository.start_run("owner", run.id)
        with pytest.raises(UnsafeAgentPayloadError):
            repository.append_step(
                user_id="owner",
                run_id=run.id,
                node_name="execute_tool",
                tool_name="mock",
                parameters={"nested": {"chain_of_thought": "不得保存"}},
            )
        for sequence in range(2):
            repository.append_step(
                user_id="owner",
                run_id=run.id,
                node_name=f"node-{sequence}",
                tool_name=None,
                parameters={},
            )
        with pytest.raises(AgentStateConflictError):
            repository.append_step(
                user_id="owner",
                run_id=run.id,
                node_name="too-many",
                tool_name=None,
                parameters={},
            )
        repository.stop_run("owner", run.id)
        with pytest.raises(AgentStateConflictError):
            repository.complete_run(
                "owner",
                run.id,
                final_result="不允许",
                used_tokens=0,
                estimated_cost_cny=0,
            )
    engine.dispose()
