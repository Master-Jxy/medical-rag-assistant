"""Structured vision orchestration with ownership, quotas, usage and idempotency."""

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import VisionUnavailableError
from app.infrastructure.dashscope_vision import DashScopeVisionChatAdapter
from app.infrastructure.fake_vision import DisabledVisionChatAdapter, FakeVisionChatAdapter
from app.modules.media.service import MediaAssetService
from app.modules.usage.quota_service import build_quota_gate
from app.modules.usage.service import ModelUsageRecorder
from app.modules.vision.contracts import VisionChatPort, VisionObservation
from app.modules.vision.models import VisionObservationRecord
from app.modules.vision.policy import OVERVIEW_HASH, assert_call_allowed, focus_hash


def build_vision_adapter(settings: Settings) -> VisionChatPort:
    if not settings.vision_chat_enabled or settings.vision_provider == "disabled":
        return DisabledVisionChatAdapter()
    if settings.vision_provider == "fake":
        return FakeVisionChatAdapter()
    return DashScopeVisionChatAdapter(settings)


class VisionChatService:
    def __init__(self, session: Session, settings: Settings, *, adapter: VisionChatPort | None = None, quota_gate=None, usage_recorder: ModelUsageRecorder | None = None) -> None:
        self.session = session
        self.settings = settings
        self.adapter = adapter or build_vision_adapter(settings)
        self.quota_gate = quota_gate or build_quota_gate(session, settings)
        self.usage_recorder = usage_recorder or ModelUsageRecorder(session, settings)
        self.media = MediaAssetService(session, settings)

    def observe_overview(self, *, user_id: str, asset_id: str, user_question: str, surface: str, usage_group_id: str) -> VisionObservation:
        return self._observe(user_id=user_id, asset_id=asset_id, user_question=user_question, focus_instruction=None, surface=surface, usage_group_id=usage_group_id)

    def inspect(self, *, user_id: str, asset_id: str, user_question: str, focus_instruction: str, surface: str, usage_group_id: str) -> VisionObservation:
        return self._observe(user_id=user_id, asset_id=asset_id, user_question=user_question, focus_instruction=focus_instruction, surface=surface, usage_group_id=usage_group_id)

    def _observe(self, *, user_id: str, asset_id: str, user_question: str, focus_instruction: str | None, surface: str, usage_group_id: str) -> VisionObservation:
        if surface not in {"vision_rag", "vision_agent"}:
            raise ValueError("invalid vision surface")
        asset = self.media.owned_asset(user_id, asset_id)
        requested_hash = focus_hash(focus_instruction)
        existing = self._existing(user_id, asset_id, usage_group_id, requested_hash)
        if existing and existing.status == "completed" and existing.observation_json:
            return VisionObservation.model_validate(existing.observation_json)
        completed = list(self.session.scalars(select(VisionObservationRecord).where(VisionObservationRecord.user_id == user_id, VisionObservationRecord.media_asset_id == asset_id, VisionObservationRecord.status == "completed").order_by(VisionObservationRecord.sequence_no)))
        assert_call_allowed(completed_hashes=[item.focus_instruction_hash or OVERVIEW_HASH for item in completed], requested_hash=requested_hash, max_calls=self.settings.vision_max_calls_per_image)
        if requested_hash != OVERVIEW_HASH and not any((item.focus_instruction_hash or OVERVIEW_HASH) == OVERVIEW_HASH for item in completed):
            raise VisionUnavailableError("请先完成图片整体观察，再进行定向观察")
        record = existing or VisionObservationRecord(
            media_asset_id=asset_id, user_id=user_id,
            run_id=usage_group_id if surface == "vision_agent" else None,
            assistant_message_id=usage_group_id if surface == "vision_rag" else None,
            kind="overview" if requested_hash == OVERVIEW_HASH else "focused",
            focus_instruction_hash=requested_hash,
            model_name=self.settings.vision_model,
            status="pending", sequence_no=len(completed) + 1,
        )
        if existing is None:
            self.session.add(record)
            self.session.commit()
        reservation = None
        quota_key = f"vision:{user_id}:{asset_id}:{usage_group_id}:{requested_hash}"
        try:
            reservation = self.quota_gate.reserve(
                user_id=user_id, surface=surface, idempotency_key=quota_key,
                requested_tokens=(self.settings.vision_reserve_input_tokens + self.settings.vision_reserve_output_tokens),
                estimated_input_tokens=self.settings.vision_reserve_input_tokens,
                estimated_output_tokens=self.settings.vision_reserve_output_tokens,
                input_price_per_million_tokens_cny=self.settings.vision_input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=self.settings.vision_output_price_per_million_tokens_cny,
                usage_group_id=usage_group_id,
            )
            path, _mime, _name = self.media.preview(user_id, asset_id)
            result = self.adapter.observe(
                image_bytes=path.read_bytes(), mime_type=asset.mime_type,
                user_question=user_question, focus_instruction=focus_instruction,
            )
            observation = result.observation
            if not observation.summary.strip():
                raise VisionUnavailableError("图片识别未返回有效结果")
            normalized = json.dumps(observation.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            if any(json.dumps(item.observation_json, ensure_ascii=False, sort_keys=True) == normalized for item in completed if item.observation_json):
                raise VisionUnavailableError("定向观察未获得新增信息，已停止继续调用")
            self.usage_recorder.record(
                call_id=f"vision:{record.id}", request_id=None, user_id=user_id,
                surface=surface, operation=record.kind, model_name=result.model_name,
                usage=result.usage,
                input_price_per_million_tokens_cny=self.settings.vision_input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=self.settings.vision_output_price_per_million_tokens_cny,
                usage_group_id=usage_group_id,
            )
            record.model_name = result.model_name
            record.status = "completed"
            record.observation_json = observation.model_dump(mode="json")
            record.input_tokens = result.usage.input_tokens
            record.output_tokens = result.usage.output_tokens
            record.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            if reservation is not None:
                self.quota_gate.settle(reservation.id, result.usage)
            return observation
        except Exception as exc:
            self.session.rollback()
            failed = self.session.get(VisionObservationRecord, record.id)
            if failed is not None and failed.status != "completed":
                failed.status = "failed"
                failed.error_code = getattr(exc, "code", type(exc).__name__)[:100]
                failed.completed_at = datetime.now(timezone.utc)
                self.session.commit()
            if reservation is not None:
                self.quota_gate.release(reservation.id)
            if isinstance(exc, VisionUnavailableError):
                raise
            raise

    def _existing(self, user_id: str, asset_id: str, usage_group_id: str, requested_hash: str) -> VisionObservationRecord | None:
        statement = select(VisionObservationRecord).where(
            VisionObservationRecord.user_id == user_id,
            VisionObservationRecord.media_asset_id == asset_id,
            VisionObservationRecord.focus_instruction_hash == requested_hash,
        )
        records = list(self.session.scalars(statement))
        return next((item for item in records if item.run_id == usage_group_id or item.assistant_message_id == usage_group_id), None)
