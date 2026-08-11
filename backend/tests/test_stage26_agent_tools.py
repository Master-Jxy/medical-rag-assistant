"""Stage 26.5 deterministic Agent tools and governance tests."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.modules.agent.contracts import AgentToolArguments, AgentToolContext, AgentToolResult
from app.modules.agent.deterministic_tools import (
    CalculatorTool,
    DraftFollowUpPlanTool,
    ExtractMeasurementsTool,
    ExtractTableTool,
    GetDocumentSectionTool,
    VerifyCitationsTool,
    stage26_tool_definitions,
)
from app.modules.agent.mode_policy import KNOWLEDGE_TOOLS, VISION_TOOLS
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.planner import FinalDecision, InspectionDecision, PlanDecision, ToolDecision
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.state import AgentRunStatus, create_initial_state
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.roles import UserRole
from app.modules.auth.schemas import UserResponse


class Info:
    def __init__(self, document_id: str, status: str = "published") -> None:
        self.document_id = document_id
        self.status = status
        self.file_name = f"{document_id}.md"
        self.source = "人工审核资料"
        self.tags = ()
        self.version = 1
        self.chunk_count = 1
        self.created_at = datetime.now(timezone.utc)


class StructuredCatalog:
    def __init__(self) -> None:
        self.infos = {"doc-1": Info("doc-1"), "doc-archived": Info("doc-archived", "archived")}

    def get_published_document(self, document_id: str):
        return self.infos.get(document_id)

    def get_published_sections(self, document_id: str):
        if document_id != "doc-1":
            return []
        return [
            {"section_id": "sec-1", "title": "适用范围", "text": "这是已解析的结构化章节。", "level": 1, "page": 2},
        ]

    def get_published_tables(self, document_id: str):
        if document_id != "doc-1":
            return []
        return [
            {"table_id": "table-1", "caption": "指标表", "headers": ["项目", "值"], "rows": [["心率", "72"]], "page": 3},
        ]


def context(**kwargs) -> AgentToolContext:
    return AgentToolContext(run_id="run-1", user_id="user-1", **kwargs)


def parsed(tool, values):
    return tool.arguments_model.model_validate(values)


def test_calculator_is_bounded_and_never_accepts_code() -> None:
    tool = CalculatorTool()
    result = tool.invoke(context(), parsed(tool, {"expression": "(2 + 3) * 4"}))
    assert result.data["ok"] is True
    assert result.data["formatted"] == "20"

    unsafe = tool.invoke(context(), parsed(tool, {"expression": "__import__('os').getcwd()"}))
    assert unsafe.data["ok"] is False
    assert unsafe.data["error_code"] == "UNSAFE_EXPRESSION"


def test_structured_document_tools_do_not_fallback_to_free_text() -> None:
    catalog = StructuredCatalog()
    section_tool = GetDocumentSectionTool(catalog)
    section = section_tool.invoke(
        context(), parsed(section_tool, {"document_id": "doc-1", "section_id": "sec-1"})
    )
    assert section.data["found"] is True
    assert section.source_ids == ["doc-1"]

    table_tool = ExtractTableTool(catalog)
    table = table_tool.invoke(
        context(), parsed(table_tool, {"document_id": "doc-1", "table_id": "table-1"})
    )
    assert table.data["table"]["rows"] == [["心率", "72"]]
    assert table.source_ids == ["doc-1"]

    archived = section_tool.invoke(
        context(), parsed(section_tool, {"document_id": "doc-archived", "section_id": "sec-1"})
    )
    assert archived.data["found"] is False


def test_citations_require_current_run_provenance() -> None:
    tool = VerifyCitationsTool(StructuredCatalog())
    result = tool.invoke(
        context(source_ids=("doc-1", "asset-1")),
        parsed(tool, {"citation_ids": ["doc-1", "missing", "asset-1"]}),
    )
    assert result.data["valid_ids"] == ["doc-1", "asset-1"]
    assert result.data["invalid_ids"] == ["missing"]
    assert result.data["verified"] is False


def test_measurements_only_consume_structured_visual_observations() -> None:
    tool = ExtractMeasurementsTool()
    result = tool.invoke(
        context(
            visual_observations=(
                {
                    "media_asset_id": "asset-1",
                    "observation": {
                        "summary": "报告可见文字",
                        "measurements": [{"name": "心率", "value": "72", "unit": "次/分"}],
                    },
                },
            )
        ),
        parsed(tool, {}),
    )
    assert result.data["found"] is True
    assert result.data["measurements"][0]["name"] == "心率"
    assert "不构成诊断" in result.data["medical_disclaimer"]

    empty = tool.invoke(context(), parsed(tool, {}))
    assert empty.data["found"] is False


def test_follow_up_draft_is_deterministic_and_has_non_clinical_disclaimer() -> None:
    tool = DraftFollowUpPlanTool(StructuredCatalog())
    result = tool.invoke(
        context(),
        parsed(tool, {"goal": "整理检查报告，准备下次沟通", "document_ids": ["doc-1"]}),
    )
    assert len(result.data["questions"]) == 6
    assert result.source_ids == ["doc-1"]
    assert "不构成诊断" in result.data["medical_disclaimer"]

    missing = tool.invoke(
        context(), parsed(tool, {"goal": "准备复诊", "document_ids": ["missing"]})
    )
    assert missing.data["missing_document_ids"] == ["missing"]


def test_stage26_tools_have_governance_metadata_and_are_whitelisted() -> None:
    definitions = stage26_tool_definitions()
    names = {item["name"] for item in definitions}
    assert names == {
        "calculator",
        "get_document_section",
        "extract_table",
        "verify_citations",
        "extract_measurements",
        "draft_follow_up_plan",
    }
    for item in definitions:
        metadata = item["metadata"]
        assert metadata["version"] == "1.0.0"
        assert metadata["risk"] in {"low", "medium", "high"}
        assert metadata["timeout_seconds"] > 0
        assert metadata["budget"]["max_calls_per_run"] == 1
        assert metadata["cost"]["mode"] == "none"

    assert "extract_measurements" in VISION_TOOLS
    assert names.issubset(KNOWLEDGE_TOOLS)


def test_registry_exposes_metadata_without_invoking_tools() -> None:
    registry = ToolRegistry([CalculatorTool()])
    definition = registry.definitions()[0]
    assert definition["name"] == "calculator"
    assert definition["metadata"]["cost"]["mode"] == "none"


def test_authenticated_agent_tools_endpoint_exposes_stage26_catalog() -> None:
    now = datetime.now(timezone.utc)
    app.dependency_overrides[get_current_user] = lambda: UserResponse(
        id="tool-user",
        email="tool-user@example.com",
        display_name=None,
        is_active=True,
        role=UserRole.USER,
        created_at=now,
        updated_at=now,
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/agent/tools")
        assert response.status_code == 200
        body = response.json()
        assert body["catalog_version"] == "26.5"
        assert {item["name"] for item in body["tools"]} == {
            "calculator",
            "get_document_section",
            "extract_table",
            "verify_citations",
            "extract_measurements",
            "draft_follow_up_plan",
        }
    finally:
        app.dependency_overrides.clear()


class SequentialPlanner:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.index = 0

    def classify_and_plan(self, state):
        return PlanDecision(route="tool_required", plan=["执行受控工具"])

    def select_tool(self, state):
        name = self.names[min(self.index, len(self.names) - 1)]
        self.index += 1
        return ToolDecision(tool_name=name, arguments={"expression": "1 + 1"} if name == "calculator" else {})

    def inspect_result(self, state):
        return InspectionDecision(
            action="continue" if self.index < len(self.names) else "finalize",
            final_output=None if self.index < len(self.names) else "已完成。",
        )

    def finalize(self, state):
        return FinalDecision(output="已完成。")


class ObservationArguments(AgentToolArguments):
    pass


class ObservationTool:
    name = "observe_image"
    description = "返回固定结构化视觉观察"
    arguments_model = ObservationArguments

    def invoke(self, context, arguments):
        del context, arguments
        return AgentToolResult(
            summary="已观察图片",
            source_ids=["asset-1"],
            data={
                "observations": [
                    {
                        "media_asset_id": "asset-1",
                        "observation": {
                            "summary": "报告指标",
                            "measurements": [{"name": "心率", "value": "72"}],
                        },
                    }
                ]
            },
        )


def graph_state(mode: str):
    return create_initial_state(
        run_id="run-stage26",
        user_id="user-stage26",
        task="执行受控工具",
        policy=AgentPolicy(enabled=True, max_steps=3, max_tool_calls=3),
        assistant_mode=mode,
    )


def test_langgraph_enforces_per_tool_metadata_budget() -> None:
    runner = BoundedAgentGraph(
        planner=SequentialPlanner(["calculator", "calculator"]),
        registry=ToolRegistry([CalculatorTool()]),
    )
    result = runner.invoke(graph_state("knowledge"))
    assert result["status"] == AgentRunStatus.FAILED
    assert result["error_type"] == "TOOL_CALL_BUDGET_EXCEEDED"
    assert result["tool_call_counts"] == {"calculator": 1}


def test_langgraph_carries_visual_observations_to_measurement_tool() -> None:
    runner = BoundedAgentGraph(
        planner=SequentialPlanner(["observe_image", "extract_measurements"]),
        registry=ToolRegistry([ObservationTool(), ExtractMeasurementsTool()]),
    )
    result = runner.invoke(graph_state("general"))
    assert result["status"] == AgentRunStatus.COMPLETED
    assert result["tool_call_counts"] == {"observe_image": 1, "extract_measurements": 1}
    assert result["last_tool_result"]["data"]["measurements"][0]["name"] == "心率"
    assert result["tool_result_digests"][-1]["source_ids"] == ["asset-1"]
