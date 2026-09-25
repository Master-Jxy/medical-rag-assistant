"""Stage 25.4 Agent overview, knowledge-tool continuation and history tests."""

from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.models import MediaAsset, MessageAttachment, ModelUsageRecord, User, VisionObservationRecord
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.context_builder import AgentContextBuilder
from app.modules.agent.contracts import AgentToolArguments, AgentToolContext, AgentToolResult
from app.modules.agent.conversation_application import AgentConversationApplication
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.planner import FinalDecision, InspectionDecision, PlanDecision, ToolDecision
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_repository import AgentThreadRepository
from app.modules.agent.thread_schemas import AgentMessageStreamRequest
from app.modules.agent.thread_service import AgentThreadService
from app.modules.agent.message_service import AgentMessageService
from app.modules.media.storage import PrivateMediaStorage
from app.modules.media.service import MediaAssetService
from app.ports.idempotency import IdempotencyRecord, IdempotencyStatus
from app.services.generation_lock_service import GenerationLockLease
from app.services.idempotency_service import IdempotencyClaim


class NoArguments(AgentToolArguments):
    pass


class KnowledgeTool:
    name = "search_knowledge"
    description = "检索已发布知识库"
    arguments_model = NoArguments

    def invoke(self, context: AgentToolContext, arguments: AgentToolArguments) -> AgentToolResult:
        del context, arguments
        return AgentToolResult(summary="找到知识库说明", source_ids=["doc-image"], data={"items": [{"content": "白细胞升高需要结合临床资料解释"}], "count": 1})


class ImagePlanner:
    def classify_and_plan(self, state):
        assert "图片观察" in state["task"] and "白细胞计数" in state["task"]
        return PlanDecision(plan=["读取图片观察", "检索公共知识库"], specialist="knowledge_specialist")

    def select_tool(self, state):
        return ToolDecision(tool_name="search_knowledge", arguments={})

    def inspect_result(self, state):
        return InspectionDecision(action="finalize", final_output="图片观察与知识库说明已结合，不能据此作出诊断。")

    def finalize(self, state):
        return FinalDecision(output="图片观察与知识库说明已结合，不能据此作出诊断。")


class Lock:
    def acquire_agent(self, user_id, thread_id):
        return GenerationLockLease(f"agent:{user_id}:{thread_id}", "owner")

    def release(self, lease):
        del lease


class Idempotency:
    def begin_agent(self, user_id, client_request_id, thread_id, content, reference_fingerprint):
        del content, reference_fingerprint
        return IdempotencyClaim(f"{user_id}:{thread_id}:{client_request_id}", "fingerprint")

    def complete_agent(self, claim, **result):
        del claim, result

    def abandon(self, claim):
        del claim


class NoopExtraction:
    def schedule(self, *args, **kwargs):
        del args, kwargs


def test_agent_attachment_ids_are_normalized_and_bounded() -> None:
    payload = AgentMessageStreamRequest(content="", attachment_ids=["  asset-1  "])
    assert payload.attachment_ids == ["asset-1"]
    with pytest.raises(ValidationError):
        AgentMessageStreamRequest(content="", attachment_ids=["same", " same "])
    with pytest.raises(ValidationError):
        AgentMessageStreamRequest(content="", attachment_ids=["x" * 37])


def test_agent_image_overview_flows_into_knowledge_tool_and_history(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'agent-images.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(id="agent-image-user", email="agent-image@example.com", password_hash="hash")
    session.add(user); session.commit()
    settings = Settings(
        _env_file=None, media_asset_dir=tmp_path / "media",
        vision_chat_enabled=True, vision_provider="fake",
        agent_enabled=True, quota_policy_mode="off",
    )
    source = tmp_path / "report.png"
    Image.new("RGB", (30, 18), "white").save(source)
    stored = PrivateMediaStorage(settings).store(original_name="report.png", claimed_mime="image/png", data=source.read_bytes())
    asset = MediaAsset(
        user_id=user.id, original_name="report.png", mime_type=stored.mime_type,
        byte_size=stored.byte_size, width=stored.width, height=stored.height,
        sha256=stored.sha256, storage_key=stored.storage_key,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    session.add(asset); session.commit()
    thread = AgentThreadService(session).create(user.id, "图片分析", "knowledge")
    cancellation = AgentCancellationService()
    registry = ToolRegistry([KnowledgeTool()])
    service = AgentConversationApplication(
        session,
        policy=AgentPolicy(enabled=True),
        graph_factory=lambda user_id, run_id: BoundedAgentGraph(
            planner=ImagePlanner(), registry=registry,
            stop_requested=lambda: cancellation.is_requested(user_id, run_id),
        ),
        cancellation=cancellation,
        generation_lock=Lock(), idempotency=Idempotency(),
        context_builder=AgentContextBuilder(AgentThreadRepository(session), AgentRepository(session)),
        model_name="fake-agent", memory_extraction=NoopExtraction(), settings=settings,
    )
    try:
        events = list(service.stream_message(
            user_id=user.id, thread_id=thread.id,
            payload=AgentMessageStreamRequest(content="", attachment_ids=[asset.id]),
            client_request_id="agent-image", request_id="request-image",
        ))
        names = [item["event"] for item in events]
        assert "vision_observations" in names and "sources" in names and "message_completed" in names
        overview = session.scalar(select(VisionObservationRecord))
        merged = dict(overview.observation_json)
        merged["quality_summary"] = {
            "route_kind": "ocr_mode",
            "quality_status": "pass",
            "quality_codes": ["OCR_MODE_APPLIED"],
        }
        overview.observation_json = merged
        overview.route_kind = "ocr_mode"
        overview.quality_status = "pass"
        overview.quality_codes = ["OCR_MODE_APPLIED"]
        session.add_all([
            VisionObservationRecord(
                media_asset_id=overview.media_asset_id,
                user_id=overview.user_id,
                run_id=overview.run_id,
                observation_scope_id=overview.observation_scope_id,
                kind="report_extract",
                focus_instruction_hash="ocr:agent-history-filter-test",
                model_name="fake-chat-ocr",
                status="completed",
                sequence_no=2,
                route_kind="ocr_mode",
                quality_status="pass",
                quality_codes=[],
                provider_call_count=1,
                observation_json={
                    "image_type": "document",
                    "summary": "internal OCR extraction",
                    "visible_text": ["INTERNAL ONLY"],
                    "quality_summary": {
                        "route_kind": "ocr_mode",
                        "quality_status": "pass",
                        "quality_codes": [],
                    },
                },
            ),
            VisionObservationRecord(
                media_asset_id=overview.media_asset_id,
                user_id=overview.user_id,
                run_id=overview.run_id,
                observation_scope_id=overview.observation_scope_id,
                kind="focused",
                focus_instruction_hash="focused-history-test",
                model_name="fake-vision",
                status="completed",
                sequence_no=3,
                route_kind="general",
                quality_status="pass",
                quality_codes=[],
                provider_call_count=1,
                observation_json={
                    "image_type": "photo",
                    "summary": "public focused observation",
                    "objects": ["focused marker"],
                    "quality_summary": {
                        "route_kind": "general",
                        "quality_status": "pass",
                        "quality_codes": [],
                    },
                },
            ),
        ])
        session.commit()
        messages = AgentMessageService(session).list(user.id, thread.id, offset=0, limit=20)
        assert messages[0].attachments[0]["media_asset_id"] == asset.id
        assert messages[1].vision_observations[0]["observation"]["image_type"] == "medical_report"
        assert [item["kind"] for item in messages[1].vision_observations] == [
            "overview",
            "focused",
        ]
        assert messages[1].vision_observations[0]["observation"]["quality_summary"] == {
            "route_kind": "ocr_mode",
            "quality_status": "pass",
            "quality_codes": ["OCR_MODE_APPLIED"],
        }
        assert "不能据此作出诊断" in messages[1].content
        observation = session.scalar(select(VisionObservationRecord).where(
            VisionObservationRecord.kind == "overview"
        ))
        attachment = session.scalar(select(MessageAttachment))
        assert observation.run_id == messages[1].run_id
        assert attachment.agent_message_id == messages[0].id
        usage = list(session.scalars(select(ModelUsageRecord)))
        assert any(item.surface == "vision_agent" and item.total_tokens == 168 for item in usage)
        assert all(item.usage_group_id == messages[1].id for item in usage)

        original_run = AgentRepository(session).list_runs(user.id)[0]
        original_run.status = "failed"
        session.commit()
        observation_count = len(list(session.scalars(select(VisionObservationRecord))))
        stopped_retry = service.retry_message(
            user_id=user.id,
            message_id=messages[0].id,
            client_request_id="agent-image-stop-retry",
            request_id="request-image-stop-retry",
        )
        created = next(stopped_retry)
        assert created["event"] == "message_created"
        cancellation.request_stop(user.id, created["data"]["run_id"])
        stopped_events = list(stopped_retry)
        assert stopped_events[-1]["event"] == "message_completed"
        assert stopped_events[-1]["data"]["status"] == "stopped"
        assert len(list(session.scalars(select(VisionObservationRecord)))) == observation_count

        retry_messages = AgentMessageService(session).list(
            user.id, thread.id, offset=0, limit=20
        )
        stopped_user_message = retry_messages[2]
        assert stopped_user_message.attachments[0]["media_asset_id"] == asset.id
        assert len(list(session.scalars(select(MessageAttachment)))) == 1

        completed_retry_events = list(service.retry_message(
            user_id=user.id,
            message_id=stopped_user_message.id,
            client_request_id="agent-image-complete-retry",
            request_id="request-image-complete-retry",
        ))
        assert completed_retry_events[-1]["event"] == "message_completed"
        assert completed_retry_events[-1]["data"]["status"] == "completed"
        final_messages = AgentMessageService(session).list(
            user.id, thread.id, offset=0, limit=20
        )
        assert final_messages[4].attachments[0]["media_asset_id"] == asset.id
        assert len(list(session.scalars(select(MessageAttachment)))) == 1

        stored_path = PrivateMediaStorage(settings).resolve(asset.storage_key)
        assert stored_path.exists()
        AgentThreadService(
            session,
            media_service=MediaAssetService(session, settings),
        ).delete(user.id, thread.id)
        assert session.get(MediaAsset, asset.id).status == "deleted"
        assert not stored_path.exists()
    finally:
        session.close(); engine.dispose()
