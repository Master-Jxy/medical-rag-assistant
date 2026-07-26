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
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import ToolRegistry
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.roles import UserRole
from app.modules.auth.schemas import UserResponse


class NoArguments(AgentToolArguments):
    pass


class ReportTool:
    name = "report_tool"
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
        return PlanDecision(plan=["生成学习报告"])

    def select_tool(self, state):
        return ToolDecision(tool_name="report_tool", arguments={})

    def inspect_result(self, state):
        return InspectionDecision(action="finalize", final_output="学习报告已完成。")

    def finalize(self, state):
        return FinalDecision(output="学习报告已完成。")


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
            created = client.post(
                "/api/v1/agent/runs",
                json={"task": "整理患者安全资料"},
            )
            assert created.status_code == 201
            run_id = created.json()["id"]

            streamed = client.post(f"/api/v1/agent/runs/{run_id}/stream")
            assert streamed.status_code == 200
            assert "event: run_started" in streamed.text
            assert "event: plan_ready" in streamed.text
            assert "event: tool_started" in streamed.text
            assert "event: artifact_ready" in streamed.text
            assert "event: run_completed" in streamed.text
            assert "学习报告已完成" in streamed.text

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


def test_agent_create_respects_default_off_switch() -> None:
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
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "AGENT_DISABLED"
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
