"""任务13.1：Agent会话、消息、用户隔离与级联清理。"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.agent.models import AgentArtifact, AgentRun, AgentStep
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_models import AgentMessage, AgentThread
from app.modules.agent.thread_repository import (
    AgentMessageNotFoundError,
    AgentThreadNotFoundError,
    AgentThreadRepository,
    UnsafeAgentMessageMetadataError,
)
from app.modules.agent.thread_schemas import (
    AgentMessageResponse,
    AgentThreadResponse,
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


def test_threads_are_isolated_and_support_rename_and_archive() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        create_user(session, "other")
        repository = AgentThreadRepository(session)
        thread = repository.create_thread(
            user_id="owner",
            title="  患者安全资料  ",
        )

        assert thread.title == "患者安全资料"
        assert repository.list_threads("owner") == [thread]
        assert repository.list_threads("other") == []
        with pytest.raises(AgentThreadNotFoundError):
            repository.get_thread("other", thread.id)
        with pytest.raises(AgentThreadNotFoundError):
            repository.rename_thread("other", thread.id, "越权修改")
        with pytest.raises(AgentThreadNotFoundError):
            repository.archive_thread("other", thread.id)

        repository.rename_thread("owner", thread.id, "患者安全报告")
        repository.archive_thread("owner", thread.id)
        assert repository.list_threads("owner", status="active") == []
        assert repository.list_threads("owner", status="archived") == [thread]
        repository.archive_thread("owner", thread.id, archived=False)
        assert thread.status == "active"
    engine.dispose()


def test_messages_are_isolated_and_metadata_is_whitelisted() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        create_user(session, "other")
        repository = AgentThreadRepository(session)
        owner_thread = repository.create_thread(user_id="owner")
        other_thread = repository.create_thread(user_id="other")
        other_message = repository.create_message(
            user_id="other",
            thread_id=other_thread.id,
            role="user",
            content="其他用户消息",
        )
        user_message = repository.create_message(
            user_id="owner",
            thread_id=owner_thread.id,
            role="user",
            content="整理这份资料",
            metadata={"referenced_message_ids": []},
        )
        assistant_message = repository.create_message(
            user_id="owner",
            thread_id=owner_thread.id,
            role="assistant",
            content="已完成",
            reply_to_message_id=user_message.id,
            metadata={
                "source_ids": ["doc-1"],
                "artifact_ids": ["artifact-1"],
            },
        )

        assert repository.list_messages("owner", owner_thread.id) == [
            user_message,
            assistant_message,
        ]
        assert AgentThreadResponse.model_validate(owner_thread).id == owner_thread.id
        assert AgentMessageResponse.model_validate(
            assistant_message
        ).metadata == {
            "source_ids": ["doc-1"],
            "artifact_ids": ["artifact-1"],
        }
        with pytest.raises(AgentThreadNotFoundError):
            repository.list_messages("other", owner_thread.id)
        with pytest.raises(AgentMessageNotFoundError):
            repository.get_message("other", owner_thread.id, user_message.id)
        with pytest.raises(AgentMessageNotFoundError):
            repository.create_message(
                user_id="owner",
                thread_id=owner_thread.id,
                role="assistant",
                content="禁止跨会话回复",
                reply_to_message_id=other_message.id,
            )
        with pytest.raises(UnsafeAgentMessageMetadataError):
            repository.create_message(
                user_id="owner",
                thread_id=owner_thread.id,
                role="assistant",
                content="禁止任意字段",
                metadata={"raw_model_response": "secret"},
            )
        with pytest.raises(UnsafeAgentMessageMetadataError):
            repository.create_message(
                user_id="owner",
                thread_id=owner_thread.id,
                role="assistant",
                content="禁止隐藏推理",
                metadata={"source_ids": [{"scratchpad": "secret"}]},
            )
        with pytest.raises(UnsafeAgentMessageMetadataError):
            repository.create_message(
                user_id="owner",
                thread_id=owner_thread.id,
                role="assistant",
                content="禁止错误引用结构",
                metadata={"source_ids": "doc-1"},
            )
    engine.dispose()


def test_delete_thread_cascades_messages_runs_steps_and_artifacts() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        create_user(session, "other")
        thread_repository = AgentThreadRepository(session)
        run_repository = AgentRepository(session)
        thread = thread_repository.create_thread(
            user_id="owner",
            title="待删除会话",
        )
        unrelated_thread = thread_repository.create_thread(
            user_id="other",
            title="保留会话",
        )
        trigger_message = thread_repository.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="user",
            content="生成报告",
        )
        run = run_repository.create_run(
            user_id="owner",
            task="生成报告",
            policy=AgentPolicy(),
            model_name="mock",
        )
        run.thread_id = thread.id
        run.trigger_message_id = trigger_message.id
        run_repository.start_run("owner", run.id)
        step = run_repository.append_step(
            user_id="owner",
            run_id=run.id,
            node_name="execute_tool",
            tool_name="generate_learning_report",
            parameters={},
        )
        run_repository.finish_step(
            user_id="owner",
            step_id=step.id,
            status="completed",
            result_summary="报告已生成",
            duration_ms=10,
        )
        artifact = run_repository.add_artifact(
            user_id="owner",
            run_id=run.id,
            artifact_type="learning_report",
            file_name="report.md",
            mime_type="text/markdown",
            content="# 报告",
            source_ids=["doc-1"],
        )
        response_message = thread_repository.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="assistant",
            content="报告已生成",
            run_id=run.id,
            reply_to_message_id=trigger_message.id,
            metadata={
                "source_ids": ["doc-1"],
                "artifact_ids": [artifact.id],
            },
        )
        run.response_message_id = response_message.id
        thread.summary_until_message_id = trigger_message.id
        run_repository.complete_run(
            "owner",
            run.id,
            final_result="报告已生成",
            used_tokens=0,
            estimated_cost_cny=0,
        )
        session.commit()

        with pytest.raises(AgentThreadNotFoundError):
            thread_repository.delete_thread("other", thread.id)
        thread_repository.delete_thread("owner", thread.id)
        session.commit()

        assert session.get(AgentThread, thread.id) is None
        assert session.scalar(
            select(func.count()).select_from(AgentMessage).where(
                AgentMessage.thread_id == thread.id
            )
        ) == 0
        assert session.get(AgentRun, run.id) is None
        assert session.get(AgentStep, step.id) is None
        assert session.get(AgentArtifact, artifact.id) is None
        assert session.get(AgentThread, unrelated_thread.id) is not None
    engine.dispose()


def test_legacy_run_creation_remains_unlinked_and_readable() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        repository = AgentRepository(session)
        run = repository.create_run(
            user_id="owner",
            task="旧版独立任务",
            policy=AgentPolicy(),
        )
        session.commit()

        saved = repository.get_run("owner", run.id)
        assert saved.thread_id is None
        assert saved.trigger_message_id is None
        assert saved.response_message_id is None
    engine.dispose()


def test_message_first_page_returns_the_most_recent_rows_in_display_order() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        repository = AgentThreadRepository(session)
        thread = repository.create_thread(user_id="owner")
        messages = [
            repository.create_message(
                user_id="owner",
                thread_id=thread.id,
                role="user",
                content=f"消息{index}",
            )
            for index in range(5)
        ]
        session.commit()

        assert repository.list_messages(
            "owner",
            thread.id,
            offset=0,
            limit=2,
        ) == messages[-2:]
        assert repository.list_messages(
            "owner",
            thread.id,
            offset=2,
            limit=2,
        ) == messages[1:3]
    engine.dispose()


def test_message_sequence_is_stable_when_timestamps_are_identical() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        create_user(session, "owner")
        repository = AgentThreadRepository(session)
        thread = repository.create_thread(user_id="owner")
        user_sequence, assistant_sequence, turn_id = repository.reserve_turn(
            "owner", thread.id
        )
        user_message = repository.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="user",
            content="先问",
            sequence_no=user_sequence,
            turn_id=turn_id,
        )
        assistant_message = repository.create_message(
            user_id="owner",
            thread_id=thread.id,
            role="assistant",
            content="后答",
            sequence_no=assistant_sequence,
            turn_id=turn_id,
        )
        same_time = datetime(2026, 7, 26, tzinfo=timezone.utc)
        user_message.created_at = same_time
        assistant_message.created_at = same_time
        session.commit()

        assert repository.list_messages("owner", thread.id) == [
            user_message,
            assistant_message,
        ]
        assert (user_message.sequence_no, assistant_message.sequence_no) == (1, 2)
        assert user_message.turn_id == assistant_message.turn_id == turn_id
        assert thread.next_message_sequence == 3
    engine.dispose()
