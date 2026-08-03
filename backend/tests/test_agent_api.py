"""任务11.6：独立Agent REST/SSE、认证和产物下载。"""

from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.api.agent import get_agent_application_service
from app.db.base import Base
from app.db.session import build_engine
from app.main import app
from app.models import User
from app.modules.agent.application import AgentApplicationService
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.contracts import (
    AgentGeneratedArtifact,
    AgentToolArguments,
    AgentToolContext,
    AgentToolResult,
)
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.planner import (
    FinalDecision,
    InspectionDecision,
    PlanDecision,
    ToolDecision,
)
from app.modules.agent.generation import GeneratedAgentTextChunk
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import ToolRegistry
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.roles import UserRole
from app.modules.auth.schemas import UserResponse


class NoArguments(AgentToolArguments):
    pass


class ReportTool:
    name = "generate_learning_report"
    description = "生成固定报告"
    arguments_model = NoArguments

    def invoke(self, context: AgentToolContext, arguments: AgentToolArguments):
        return AgentToolResult(
            summary="报告已生成",
            source_ids=["doc-1"],
            artifacts=[
                AgentGeneratedArtifact(
                    artifact_type="learning_report",
                    file_name="学习报告.md",
                    mime_type="text/markdown",
                    content="# 学习报告",
                    source_ids=["doc-1"],
                )
            ],
            used_tokens=25,
            estimated_cost_cny=0.002,
        )


class ReportPlanner:
    def classify_and_plan(self, state):
        return PlanDecision(
            plan=["生成学习报告"],
            specialist="knowledge_specialist",
            handoff_to="knowledge_specialist",
        )

    def select_tool(self, state):
        return ToolDecision(tool_name="generate_learning_report", arguments={})

    def inspect_result(self, state):
        return InspectionDecision(action="finalize", final_output="学习报告已完成。")

    def finalize(self, state):
        return FinalDecision(output="学习报告已完成。")


class StreamingReportPlanner(ReportPlanner):
    def inspect_result(self, state):
        return InspectionDecision(action="finalize")

    def stream_finalize(self, state):
        yield GeneratedAgentTextChunk(content="学习报告")
        yield GeneratedAgentTextChunk(content="已完成。")
        yield GeneratedAgentTextChunk(
            content="",
            used_tokens=31,
            estimated_cost_cny=0.003,
        )


class StreamingDirectReplyPlanner(StreamingReportPlanner):
    def classify_and_plan(self, state):
        return PlanDecision(
            route="direct_reply",
            response_message="这段规划阶段的完整回答不应整块发送。",
        )

    def stream_finalize(self, state):
        yield GeneratedAgentTextChunk(content="第一段")
        yield GeneratedAgentTextChunk(content="第二段")
        yield GeneratedAgentTextChunk(content="", used_tokens=12)


def test_agent_rest_sse_persistence_and_download() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="agent-owner",
        email="agent-owner@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    cancellation = AgentCancellationService()
    registry = ToolRegistry([ReportTool()])
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda user_id, run_id: BoundedAgentGraph(
            planner=ReportPlanner(),
            registry=registry,
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
        ),
        cancellation=cancellation,
        model_name="mock",
    )
    current_user = UserResponse.model_validate(user)
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_agent_application_service] = lambda: service
    try:
        with TestClient(app) as client:
            blocked = client.post(
                "/api/v1/agent/runs",
                json={"task": "整理患者安全资料"},
            )
            assert blocked.status_code == 405
            created = service.create_run(
                "agent-owner",
                "整理患者安全资料",
            )
            run_id = created.id

            streamed = client.post(f"/api/v1/agent/runs/{run_id}/stream")
            assert streamed.status_code == 200
            assert "event: run_started" in streamed.text
            assert "event: plan_ready" in streamed.text
            assert "event: tool_started" in streamed.text
            assert "event: artifact_ready" in streamed.text
            assert "event: run_completed" in streamed.text
            assert "学习报告已完成" in streamed.text
            assert '"public_code": "handoff_completed"' in streamed.text
            assert '"public_code": "tool_started"' in streamed.text
            assert '"specialist": "knowledge_specialist"' in streamed.text
            assert "chain_of_thought" not in streamed.text
            assert "scratchpad" not in streamed.text

            detail = client.get(f"/api/v1/agent/runs/{run_id}")
            payload = detail.json()
            assert payload["status"] == "completed"
            assert payload["step_count"] == 1
            assert payload["used_tokens"] == 25
            assert payload["estimated_cost_cny"] == 0.002
            assert len(payload["steps"]) == 1
            assert len(payload["artifacts"]) == 1
            artifact_id = payload["artifacts"][0]["id"]

            downloaded = client.get(
                f"/api/v1/agent/artifacts/{artifact_id}/download"
            )
            assert downloaded.status_code == 200
            assert downloaded.content.decode("utf-8") == "# 学习报告"
            assert "filename*=UTF-8" in downloaded.headers["content-disposition"]

            listing = client.get("/api/v1/agent/runs")
            assert [item["id"] for item in listing.json()["items"]] == [run_id]
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_legacy_run_creation_endpoint_is_not_exposed() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="disabled-user",
        email="disabled@example.com",
        password_hash="hash",
        role=UserRole.USER,
    )
    session.add(user)
    session.commit()
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=False),
        graph_factory=lambda *_: None,
        cancellation=AgentCancellationService(),
    )
    app.dependency_overrides[get_current_user] = lambda: UserResponse.model_validate(user)
    app.dependency_overrides[get_agent_application_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/agent/runs",
                json={"task": "不应创建"},
            )
            assert response.status_code == 405
            assert service.list_runs(
                "disabled-user",
                offset=0,
                limit=20,
            ).items == []
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_agent_final_answer_is_forwarded_as_multiple_sse_tokens() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="stream-owner",
        email="stream-owner@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    cancellation = AgentCancellationService()
    registry = ToolRegistry([ReportTool()])
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda user_id, run_id: BoundedAgentGraph(
            planner=StreamingReportPlanner(),
            registry=registry,
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
        ),
        cancellation=cancellation,
        model_name="mock-stream",
    )
    current_user = UserResponse.model_validate(user)
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_agent_application_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = service.create_run("stream-owner", "生成流式学习报告")
            response = client.post(f"/api/v1/agent/runs/{created.id}/stream")

            assert response.status_code == 200
            assert response.text.count("event: token") == 2
            assert "学习报告" in response.text
            assert "已完成。" in response.text

            detail = client.get(f"/api/v1/agent/runs/{created.id}").json()
            assert detail["final_result"] == "学习报告已完成。"
            assert detail["used_tokens"] == 56
            assert detail["estimated_cost_cny"] == 0.005
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_agent_direct_reply_also_uses_the_streaming_finalizer() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(
        id="direct-stream-owner",
        email="direct-stream-owner@example.com",
        password_hash="hash",
    )
    session.add(user)
    session.commit()
    cancellation = AgentCancellationService()
    service = AgentApplicationService(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda user_id, run_id: BoundedAgentGraph(
            planner=StreamingDirectReplyPlanner(),
            registry=ToolRegistry([]),
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
        ),
        cancellation=cancellation,
        model_name="mock-direct-stream",
    )
    app.dependency_overrides[get_current_user] = lambda: UserResponse.model_validate(user)
    app.dependency_overrides[get_agent_application_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = service.create_run("direct-stream-owner", "你好")
            response = client.post(f"/api/v1/agent/runs/{created.id}/stream")

            assert response.status_code == 200
            assert response.text.count("event: token") == 2
            assert "第一段" in response.text
            assert "第二段" in response.text
            assert "规划阶段的完整回答" not in response.text

            detail = client.get(f"/api/v1/agent/runs/{created.id}").json()
            assert detail["final_result"] == "第一段第二段"
            assert detail["used_tokens"] == 12
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
