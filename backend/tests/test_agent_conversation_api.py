"""任务13.3-13.4：Agent会话REST/SSE、幂等、run关联和刷新恢复。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.agent import get_agent_conversation_application_service
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import User
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.context_builder import AgentContextBuilder
from app.modules.agent.contracts import (
    AgentGeneratedArtifact,
    AgentToolArguments,
    AgentToolContext,
    AgentToolResult,
)
from app.modules.agent.conversation_application import AgentConversationApplication
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.planner import (
    FinalDecision,
    InspectionDecision,
    PlanDecision,
    ToolDecision,
)
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.repository import AgentRepository
from app.modules.agent.recovery import AgentRecoveryService
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.thread_repository import AgentThreadRepository
from app.modules.agent.thread_schemas import AgentMessageStreamRequest
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.ports.idempotency import IdempotencyRecord, IdempotencyStatus
from app.services.chat_rate_limit_service import get_chat_rate_limit_service
from app.services.generation_lock_service import GenerationLockLease
from app.services.idempotency_service import IdempotencyClaim


class NoArguments(AgentToolArguments):
    pass


class ReportTool:
    name = "report_tool"
    description = "生成固定报告"
    arguments_model = NoArguments

    def invoke(self, context: AgentToolContext, arguments: AgentToolArguments):
        del context, arguments
        return AgentToolResult(
            summary="报告已生成",
            source_ids=["doc-1"],
            artifacts=[
                AgentGeneratedArtifact(
                    artifact_type="learning_report",
                    file_name="报告.md",
                    mime_type="text/markdown",
                    content="# 报告",
                    source_ids=["doc-1"],
                )
            ],
        )


class ReportPlanner:
    def classify_and_plan(self, state):
        assert "当前任务" in state["task"]
        return PlanDecision(plan=["生成报告"])

    def select_tool(self, state):
        return ToolDecision(tool_name="report_tool", arguments={})

    def inspect_result(self, state):
        return InspectionDecision(action="finalize", final_output="报告已完成。")

    def finalize(self, state):
        return FinalDecision(output="报告已完成。")


class AllowingAgentLock:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire_agent(self, user_id: str, thread_id: str):
        self.acquired += 1
        return GenerationLockLease(
            f"agent:{user_id}:{thread_id}",
            f"owner-{self.acquired}",
        )

    def release(self, lease) -> None:
        assert lease.key.startswith("agent:")
        self.released += 1


class RecordingAgentIdempotency:
    def __init__(self) -> None:
        self.records: dict[str, IdempotencyRecord] = {}
        self.abandoned = 0

    def begin_agent(
        self,
        user_id,
        client_request_id,
        thread_id,
        content,
        reference_fingerprint,
    ):
        del content, reference_fingerprint
        key = f"{user_id}:{thread_id}:{client_request_id}"
        record = self.records.get(key)
        return IdempotencyClaim(
            key,
            "fingerprint",
            record if record and record.status is IdempotencyStatus.COMPLETED else None,
        )

    def complete_agent(
        self,
        claim,
        *,
        request_id,
        thread_id,
        user_message_id,
        assistant_message_id,
    ):
        self.records[claim.key] = IdempotencyRecord(
            status=IdempotencyStatus.COMPLETED,
            request_id=request_id,
            conversation_id=thread_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
        )

    def abandon(self, claim):
        del claim
        self.abandoned += 1


class AllowingRateLimit:
    def check(self, user_id: str) -> None:
        assert user_id


def build_service(session: Session, lock, idempotency, planner=None):
    cancellation = AgentCancellationService()
    registry = ToolRegistry([ReportTool()])
    return AgentConversationApplication(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda user_id, run_id: BoundedAgentGraph(
            planner=planner or ReportPlanner(),
            registry=registry,
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
        ),
        cancellation=cancellation,
        generation_lock=lock,
        idempotency=idempotency,
        context_builder=AgentContextBuilder(
            AgentThreadRepository(session),
            AgentRepository(session),
        ),
        model_name="mock",
    )


def test_agent_thread_api_streams_persists_and_replays_without_duplicate_run() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="owner",
        email="owner@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    lock = AllowingAgentLock()
    idempotency = RecordingAgentIdempotency()
    service = build_service(session, lock, idempotency)
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: UserResponse.model_validate(
        user
    )
    app.dependency_overrides[
        get_agent_conversation_application_service
    ] = lambda: service
    app.dependency_overrides[get_chat_rate_limit_service] = AllowingRateLimit
    try:
        with TestClient(app) as client:
            created_thread = client.post(
                "/api/v1/agent/threads",
                json={"title": "患者安全"},
            )
            assert created_thread.status_code == 201
            thread_id = created_thread.json()["id"]

            response = client.post(
                f"/api/v1/agent/threads/{thread_id}/messages/stream",
                headers={"Idempotency-Key": "message-1"},
                json={
                    "content": "根据资料生成报告",
                    "source_ids": ["doc-1"],
                },
            )
            assert response.status_code == 200
            assert "event: message_created" in response.text
            assert "event: sources" in response.text
            assert "event: artifact_ready" in response.text
            assert "event: message_completed" in response.text

            messages = client.get(
                f"/api/v1/agent/threads/{thread_id}/messages"
            ).json()["items"]
            assert [item["role"] for item in messages] == ["user", "assistant"]
            assert messages[1]["status"] == "completed"
            assert messages[1]["content"] == "报告已完成。"
            assert messages[1]["metadata"]["source_ids"] == ["doc-1"]
            run_id = messages[1]["run_id"]
            run = client.get(f"/api/v1/agent/runs/{run_id}").json()
            assert run["thread_id"] == thread_id
            assert run["trigger_message_id"] == messages[0]["id"]
            assert run["response_message_id"] == messages[1]["id"]

            replay = client.post(
                f"/api/v1/agent/threads/{thread_id}/messages/stream",
                headers={"Idempotency-Key": "message-1"},
                json={
                    "content": "根据资料生成报告",
                    "source_ids": ["doc-1"],
                },
            )
            assert '"replayed": true' in replay.text
            assert len(
                client.get("/api/v1/agent/runs").json()["items"]
            ) == 1
            assert lock.acquired == 1
            assert lock.released == 1

            renamed = client.patch(
                f"/api/v1/agent/threads/{thread_id}",
                json={"title": "患者安全报告", "status": "archived"},
            )
            assert renamed.json()["title"] == "患者安全报告"
            assert renamed.json()["status"] == "archived"
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_closing_agent_conversation_stream_marks_message_stopped_and_releases() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(
            id="owner",
            email="owner@example.com",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        threads = AgentThreadRepository(session)
        thread = threads.create_thread(user_id=user.id)
        session.commit()
        lock = AllowingAgentLock()
        idempotency = RecordingAgentIdempotency()
        iterator = build_service(session, lock, idempotency).stream_message(
            user_id=user.id,
            thread_id=thread.id,
            payload=AgentMessageStreamRequest(content="生成报告"),
            client_request_id="disconnect",
            request_id="request",
        )
        assert next(iterator)["event"] == "message_created"
        iterator.close()

        messages = threads.list_messages(user.id, thread.id)
        assert messages[-1].status == "stopped"
        assert messages[-1].message_metadata["stop_reason"] == "client_disconnected"
        assert lock.released == 1
    engine.dispose()


def test_three_rounds_reuse_recent_messages_and_explicit_artifact() -> None:
    class RecordingPlanner(ReportPlanner):
        def __init__(self) -> None:
            self.contexts = []

        def classify_and_plan(self, state):
            self.contexts.append(state["task"])
            return PlanDecision(plan=["生成报告"])

    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(
            id="owner",
            email="owner@example.com",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        threads = AgentThreadRepository(session)
        thread = threads.create_thread(user_id=user.id, title="三轮任务")
        session.commit()
        planner = RecordingPlanner()
        lock = AllowingAgentLock()
        idempotency = RecordingAgentIdempotency()
        service = build_service(session, lock, idempotency, planner)

        list(
            service.stream_message(
                user_id=user.id,
                thread_id=thread.id,
                payload=AgentMessageStreamRequest(content="第一轮生成报告"),
                client_request_id="round-1",
                request_id="request-1",
            )
        )
        first_assistant = threads.list_messages(user.id, thread.id)[1]
        artifact_id = first_assistant.message_metadata["artifact_ids"][0]
        list(
            service.stream_message(
                user_id=user.id,
                thread_id=thread.id,
                payload=AgentMessageStreamRequest(
                    content="根据刚才结果补充风险"
                ),
                client_request_id="round-2",
                request_id="request-2",
            )
        )
        list(
            service.stream_message(
                user_id=user.id,
                thread_id=thread.id,
                payload=AgentMessageStreamRequest(
                    content="基于上一轮产物给出总结",
                    artifact_ids=[artifact_id],
                ),
                client_request_id="round-3",
                request_id="request-3",
            )
        )

        assert len(threads.list_messages(user.id, thread.id)) == 6
        assert len(AgentRepository(session).list_runs(user.id)) == 3
        assert "第一轮生成报告" in planner.contexts[1]
        assert "根据刚才结果补充风险" in planner.contexts[2]
        assert "报告.md" in planner.contexts[2]
        assert lock.acquired == lock.released == 3
    engine.dispose()


def test_retry_failed_task_creates_a_new_linked_run_without_overwriting_history() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(
            id="owner",
            email="owner@example.com",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        threads = AgentThreadRepository(session)
        runs = AgentRepository(session)
        thread = threads.create_thread(user_id=user.id, title="失败任务重试")
        original_message = threads.create_message(
            user_id=user.id,
            thread_id=thread.id,
            role="user",
            content="重新生成报告",
            metadata={"source_ids": ["doc-1"]},
        )
        original_run = runs.create_run(
            user_id=user.id,
            task=original_message.content,
            policy=AgentPolicy(enabled=True),
            model_name="mock",
            thread_id=thread.id,
            trigger_message_id=original_message.id,
        )
        runs.fail_run(user.id, original_run.id, "TEST_FAILURE")
        session.commit()

        lock = AllowingAgentLock()
        service = build_service(session, lock, RecordingAgentIdempotency())
        events = list(
            service.retry_message(
                user_id=user.id,
                message_id=original_message.id,
                client_request_id="retry-1",
                request_id="request-retry",
            )
        )

        messages = threads.list_messages(user.id, thread.id)
        saved_runs = runs.list_runs(user.id)
        assert events[-1]["event"] == "message_completed"
        assert len(messages) == 3
        assert len(saved_runs) == 2
        assert messages[1].role == "user"
        assert messages[1].reply_to_message_id == original_message.id
        assert messages[1].message_metadata["source_ids"] == ["doc-1"]
        assert messages[2].role == "assistant"
        assert messages[2].status == "completed"
        assert saved_runs[0].trigger_message_id == messages[1].id
        assert saved_runs[1].id == original_run.id
        assert lock.acquired == lock.released == 1
    engine.dispose()


def test_process_restart_recovery_marks_run_step_and_message_failed() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(
            id="owner",
            email="owner@example.com",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        threads = AgentThreadRepository(session)
        runs = AgentRepository(session)
        thread = threads.create_thread(user_id=user.id)
        trigger = threads.create_message(
            user_id=user.id,
            thread_id=thread.id,
            role="user",
            content="生成报告",
        )
        run = runs.create_run(
            user_id=user.id,
            task=trigger.content,
            policy=AgentPolicy(enabled=True),
            thread_id=thread.id,
            trigger_message_id=trigger.id,
        )
        runs.start_run(user.id, run.id)
        step = runs.append_step(
            user_id=user.id,
            run_id=run.id,
            node_name="execute_tool",
            tool_name="report_tool",
            parameters={},
        )
        assistant = threads.create_message(
            user_id=user.id,
            thread_id=thread.id,
            role="assistant",
            content="",
            status="streaming",
            run_id=run.id,
            reply_to_message_id=trigger.id,
        )
        runs.link_response_message(user.id, run.id, assistant.id)
        session.commit()

        assert AgentRecoveryService(session).recover_interrupted() == (1, 1, 1)
        session.refresh(run)
        session.refresh(step)
        session.refresh(assistant)
        assert run.status == "failed"
        assert run.error_type == "AGENT_PROCESS_RESTARTED"
        assert step.status == "failed"
        assert step.error_type == "AGENT_PROCESS_RESTARTED"
        assert assistant.status == "failed"
        assert (
            assistant.message_metadata["error_code"]
            == "AGENT_PROCESS_RESTARTED"
        )
        assert assistant.content
    engine.dispose()
