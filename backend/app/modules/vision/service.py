"""Structured vision orchestration with ownership, quotas, usage and idempotency."""

import json
from datetime import datetime, timezone
from time import monotonic, sleep

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import VisionPolicyError, VisionUnavailableError
from app.infrastructure.dashscope_chat_ocr import (
    DashScopeVisionTextExtractionAdapter,
)
from app.infrastructure.dashscope_vision import DashScopeVisionChatAdapter
from app.infrastructure.fake_chat_ocr import (
    DisabledVisionTextExtractionAdapter,
    FakeVisionTextExtractionAdapter,
)
from app.infrastructure.fake_vision import DisabledVisionChatAdapter, FakeVisionChatAdapter
from app.modules.media.service import MediaAssetService
from app.modules.usage.quota_service import build_quota_gate
from app.modules.usage.service import ModelUsageRecorder
from app.modules.vision.contracts import (
    VisionChatPort,
    VisionObservation,
    VisionQualitySummary,
    VisionTextExtraction,
    VisionTextExtractionPort,
    VisionTextExtractionRequest,
)
from app.modules.vision.ocr_prompts import OCR_PROMPT_VERSION
from app.modules.vision.models import VisionObservationRecord
from app.modules.vision.policy import OVERVIEW_HASH, assert_call_allowed, focus_hash
from app.modules.vision.quality import VisionQualityGate
from app.modules.vision.repository import VisionObservationRepository


def build_vision_adapter(settings: Settings) -> VisionChatPort:
    if not settings.vision_chat_enabled or settings.vision_provider == "disabled":
        return DisabledVisionChatAdapter()
    if settings.vision_provider == "fake":
        return FakeVisionChatAdapter()
    return DashScopeVisionChatAdapter(settings)


def build_vision_text_extraction_adapter(
    settings: Settings,
) -> VisionTextExtractionPort:
    if (
        not settings.vision_ocr_mode_enabled
        or settings.vision_ocr_provider == "disabled"
    ):
        return DisabledVisionTextExtractionAdapter()
    if settings.vision_ocr_provider == "fake":
        return FakeVisionTextExtractionAdapter()
    return DashScopeVisionTextExtractionAdapter(settings)


OCR_MODE_HASH = f"ocr:{OCR_PROMPT_VERSION}"


class VisionChatService:
    def __init__(self, session: Session, settings: Settings, *, adapter: VisionChatPort | None = None, ocr_adapter: VisionTextExtractionPort | None = None, quota_gate=None, usage_recorder: ModelUsageRecorder | None = None, quality_gate: VisionQualityGate | None = None) -> None:
        self.session = session
        self.settings = settings
        self.adapter = adapter or build_vision_adapter(settings)
        self.ocr_adapter = ocr_adapter or build_vision_text_extraction_adapter(settings)
        self.quota_gate = quota_gate or build_quota_gate(session, settings)
        self.usage_recorder = usage_recorder or ModelUsageRecorder(session, settings)
        self.quality_gate = quality_gate or VisionQualityGate()
        self.media = MediaAssetService(session, settings)
        self.repository = VisionObservationRepository(session)

    def observe_overview(self, *, user_id: str, asset_id: str, user_question: str, surface: str, usage_group_id: str, run_id: str | None = None) -> VisionObservation:
        return self._observe(user_id=user_id, asset_id=asset_id, user_question=user_question, focus_instruction=None, surface=surface, usage_group_id=usage_group_id, run_id=run_id)

    def inspect(self, *, user_id: str, asset_id: str, user_question: str, focus_instruction: str, surface: str, usage_group_id: str, run_id: str | None = None) -> VisionObservation:
        return self._observe(user_id=user_id, asset_id=asset_id, user_question=user_question, focus_instruction=focus_instruction, surface=surface, usage_group_id=usage_group_id, run_id=run_id)

    def extract_text(
        self,
        *,
        user_id: str,
        asset_id: str,
        surface: str,
        usage_group_id: str,
        run_id: str | None = None,
    ) -> VisionTextExtraction:
        if surface not in {"vision_rag", "vision_agent"}:
            raise ValueError("invalid vision surface")
        observation_scope_id = self._scope_id(
            surface=surface,
            usage_group_id=usage_group_id,
            run_id=run_id,
        )
        asset = self.media.owned_asset(user_id, asset_id)
        claim = self.repository.get_or_create(
            user_id=user_id,
            media_asset_id=asset_id,
            observation_scope_id=observation_scope_id,
            kind="report_extract",
            focus_instruction_hash=OCR_MODE_HASH,
            model_name=self.settings.vision_model,
            run_id=run_id if surface == "vision_agent" else None,
            assistant_message_id=(
                observation_scope_id if surface == "vision_rag" else None
            ),
        )
        record = claim.record
        if not claim.created:
            reused = self._reuse_terminal_extraction(record)
            if reused is not None:
                return reused

        records = self.repository.list_for_asset(user_id, asset_id)
        attempted = [
            item.focus_instruction_hash
            for item in records
            if item.id != record.id and item.provider_call_count > 0
        ]
        if record.provider_call_count == 0:
            try:
                assert_call_allowed(
                    attempted_hashes=attempted,
                    requested_hash=OCR_MODE_HASH,
                    max_calls=self.settings.vision_max_calls_per_image,
                )
            except VisionPolicyError as exc:
                self._mark_failed(record.id, exc.code)
                raise
            if not any(
                item.observation_scope_id == observation_scope_id
                and item.focus_instruction_hash == OVERVIEW_HASH
                and item.status == "completed"
                for item in records
            ):
                self._mark_failed(record.id, "OVERVIEW_REQUIRED")
                raise VisionUnavailableError("请先完成图片整体观察，再进行文字提取")

        owns_provider_call = self.repository.reserve_provider_call(
            record.id,
            media_asset_id=asset_id,
            max_calls=self.settings.vision_max_calls_per_image,
        )
        if not owns_provider_call:
            current = self.repository.refresh(record.id)
            if current is not None and current.provider_call_count > 0:
                return self._wait_for_extraction(current.id)
            self._mark_failed(record.id, "VISION_CALL_LIMIT")
            raise VisionPolicyError(
                "该图片已达到最多 3 次观察上限，请上传更清晰的图片"
            )

        reservation = None
        quota_finalized = False
        provider_usage = None
        quota_key = (
            f"vision:{user_id}:{asset_id}:{observation_scope_id}:"
            f"report_extract:{OCR_MODE_HASH}"
        )
        try:
            reservation = self.quota_gate.reserve(
                user_id=user_id,
                surface=surface,
                idempotency_key=quota_key,
                requested_tokens=(
                    self.settings.vision_ocr_reserve_input_tokens
                    + self.settings.vision_ocr_reserve_output_tokens
                ),
                estimated_input_tokens=self.settings.vision_ocr_reserve_input_tokens,
                estimated_output_tokens=self.settings.vision_ocr_reserve_output_tokens,
                input_price_per_million_tokens_cny=self.settings.vision_input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=self.settings.vision_output_price_per_million_tokens_cny,
                usage_group_id=usage_group_id,
            )
            path, _mime, _name = self.media.preview(user_id, asset_id)
            result = self.ocr_adapter.extract(
                VisionTextExtractionRequest(
                    image_bytes=path.read_bytes(),
                    mime_type=asset.mime_type,
                    max_output_chars=self.settings.vision_ocr_max_output_chars,
                )
            )
            provider_usage = result.usage
            extraction = result.extraction
            self.usage_recorder.record(
                call_id=f"vision:{record.id}",
                request_id=None,
                user_id=user_id,
                surface=surface,
                operation="report_extract",
                model_name=result.model_name,
                usage=result.usage,
                input_price_per_million_tokens_cny=self.settings.vision_input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=self.settings.vision_output_price_per_million_tokens_cny,
                usage_group_id=usage_group_id,
            )
            if reservation is not None:
                self.quota_gate.settle(reservation.id, result.usage)
                quota_finalized = True
            has_content = bool(
                extraction.visible_text
                or extraction.measurements
                or extraction.table_rows
            )
            quality_codes = [] if has_content else ["OCR_NO_TEXT"]
            stored = VisionObservation(
                image_type="document",
                summary="OCR-mode 文字提取结果",
                visible_text=extraction.visible_text,
                measurements=extraction.measurements,
                table_rows=extraction.table_rows,
                uncertain_content=extraction.uncertain_content,
                quality_summary=VisionQualitySummary(
                    route_kind="ocr_mode",
                    quality_status=(
                        "review"
                        if extraction.uncertain_content or not has_content
                        else "pass"
                    ),
                    quality_codes=quality_codes,
                ),
            )
            record = self.repository.refresh(record.id) or record
            record.model_name = result.model_name
            record.status = "completed"
            record.observation_json = stored.model_dump(mode="json")
            record.route_kind = "ocr_mode"
            record.quality_status = stored.quality_summary.quality_status
            record.quality_codes = quality_codes
            record.input_tokens = result.usage.input_tokens
            record.output_tokens = result.usage.output_tokens
            record.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return extraction
        except Exception as exc:
            self.session.rollback()
            self._mark_failed(
                record.id,
                getattr(exc, "code", type(exc).__name__)[:100],
            )
            if reservation is not None and not quota_finalized:
                if provider_usage is None:
                    self.quota_gate.release(reservation.id)
                else:
                    self.quota_gate.settle(reservation.id, provider_usage)
            if isinstance(exc, VisionUnavailableError):
                raise
            raise

    def finalize_overview_route(
        self,
        *,
        user_id: str,
        asset_id: str,
        surface: str,
        usage_group_id: str,
        observation: VisionObservation,
        run_id: str | None = None,
    ) -> VisionObservation:
        observation_scope_id = self._scope_id(
            surface=surface,
            usage_group_id=usage_group_id,
            run_id=run_id,
        )
        record = self.repository.get(
            user_id=user_id,
            media_asset_id=asset_id,
            observation_scope_id=observation_scope_id,
            kind="overview",
            focus_instruction_hash=OVERVIEW_HASH,
        )
        if record is None or record.status != "completed":
            raise VisionUnavailableError("图片整体观察记录不可用")
        quality = observation.quality_summary
        if quality is None:
            raise ValueError("final vision route requires quality summary")
        record.observation_json = observation.model_dump(mode="json")
        record.route_kind = quality.route_kind
        record.quality_status = quality.quality_status
        record.quality_codes = list(quality.quality_codes)
        self.session.commit()
        return observation

    def _observe(self, *, user_id: str, asset_id: str, user_question: str, focus_instruction: str | None, surface: str, usage_group_id: str, run_id: str | None) -> VisionObservation:
        if surface not in {"vision_rag", "vision_agent"}:
            raise ValueError("invalid vision surface")
        observation_scope_id = self._scope_id(
            surface=surface,
            usage_group_id=usage_group_id,
            run_id=run_id,
        )
        asset = self.media.owned_asset(user_id, asset_id)
        requested_hash = focus_hash(focus_instruction)
        kind = "overview" if requested_hash == OVERVIEW_HASH else "focused"
        claim = self.repository.get_or_create(
            user_id=user_id,
            media_asset_id=asset_id,
            observation_scope_id=observation_scope_id,
            kind=kind,
            focus_instruction_hash=requested_hash,
            model_name=self.settings.vision_model,
            run_id=run_id if surface == "vision_agent" else None,
            assistant_message_id=(
                observation_scope_id if surface == "vision_rag" else None
            ),
        )
        record = claim.record
        if not claim.created:
            reused = self._reuse_terminal(record)
            if reused is not None:
                return reused

        records = self.repository.list_for_asset(user_id, asset_id)
        attempted = [
            item.focus_instruction_hash
            for item in records
            if item.id != record.id and item.provider_call_count > 0
        ]
        if record.provider_call_count == 0:
            try:
                assert_call_allowed(
                    attempted_hashes=attempted,
                    requested_hash=requested_hash,
                    max_calls=self.settings.vision_max_calls_per_image,
                )
            except VisionPolicyError as exc:
                self._mark_failed(record.id, exc.code)
                raise
            if requested_hash != OVERVIEW_HASH and not any(
                item.observation_scope_id == observation_scope_id
                and item.focus_instruction_hash == OVERVIEW_HASH
                and item.status == "completed"
                for item in records
            ):
                self._mark_failed(record.id, "OVERVIEW_REQUIRED")
                raise VisionUnavailableError("请先完成图片整体观察，再进行定向观察")

        owns_provider_call = self.repository.reserve_provider_call(
            record.id,
            media_asset_id=asset_id,
            max_calls=self.settings.vision_max_calls_per_image,
        )
        if not owns_provider_call:
            current = self.repository.refresh(record.id)
            if current is not None and current.provider_call_count > 0:
                return self._wait_for_result(current.id)
            self._mark_failed(record.id, "VISION_CALL_LIMIT")
            raise VisionPolicyError(
                "该图片已达到最多 3 次观察上限，请上传更清晰的图片"
            )

        record = self.repository.refresh(record.id) or record
        reservation = None
        quota_finalized = False
        provider_usage = None
        quota_key = (
            f"vision:{user_id}:{asset_id}:{observation_scope_id}:"
            f"{kind}:{requested_hash}"
        )
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
            provider_usage = result.usage
            observation = self.quality_gate.apply(result.observation)
            if not observation.summary.strip():
                raise VisionUnavailableError("图片识别未返回有效结果")
            self.usage_recorder.record(
                call_id=f"vision:{record.id}", request_id=None, user_id=user_id,
                surface=surface, operation=record.kind, model_name=result.model_name,
                usage=result.usage,
                input_price_per_million_tokens_cny=self.settings.vision_input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=self.settings.vision_output_price_per_million_tokens_cny,
                usage_group_id=usage_group_id,
            )
            if reservation is not None:
                self.quota_gate.settle(reservation.id, result.usage)
                quota_finalized = True
            previous = [
                item
                for item in self.repository.list_for_asset(user_id, asset_id)
                if item.id != record.id
                and item.observation_scope_id == observation_scope_id
                and item.status == "completed"
            ]
            normalized = self._observation_fingerprint(observation)
            if any(
                self._stored_fingerprint(item.observation_json) == normalized
                for item in previous
                if item.observation_json
            ):
                raise VisionUnavailableError("定向观察未获得新增信息，已停止继续调用")
            record = self.repository.refresh(record.id) or record
            record.model_name = result.model_name
            record.status = "completed"
            record.observation_json = observation.model_dump(mode="json")
            record.route_kind = observation.quality_summary.route_kind
            record.quality_status = observation.quality_summary.quality_status
            record.quality_codes = list(observation.quality_summary.quality_codes)
            record.input_tokens = result.usage.input_tokens
            record.output_tokens = result.usage.output_tokens
            record.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            return observation
        except Exception as exc:
            self.session.rollback()
            self._mark_failed(
                record.id,
                getattr(exc, "code", type(exc).__name__)[:100],
            )
            if reservation is not None and not quota_finalized:
                if provider_usage is None:
                    self.quota_gate.release(reservation.id)
                else:
                    self.quota_gate.settle(reservation.id, provider_usage)
            if isinstance(exc, VisionUnavailableError):
                raise
            raise

    @staticmethod
    def _scope_id(*, surface: str, usage_group_id: str, run_id: str | None) -> str:
        if surface == "vision_rag":
            return usage_group_id
        if not run_id:
            raise ValueError("vision_agent requires run_id as observation scope")
        return run_id

    def _reuse_terminal(
        self, record: VisionObservationRecord
    ) -> VisionObservation | None:
        if record.status == "completed" and record.observation_json:
            return VisionObservation.model_validate(record.observation_json)
        if record.status in {"failed", "stopped"}:
            raise VisionUnavailableError("图片观察已结束，请勿重复提交相同请求")
        return None

    def _wait_for_result(self, record_id: str) -> VisionObservation:
        deadline = monotonic() + self.settings.vision_timeout_seconds + 5
        while monotonic() < deadline:
            record = self.repository.refresh(record_id)
            if record is None:
                raise VisionUnavailableError("图片观察记录不可用")
            reused = self._reuse_terminal(record)
            if reused is not None:
                return reused
            sleep(0.02)
        raise VisionUnavailableError("相同图片观察仍在处理中，请稍后查看结果")

    def _reuse_terminal_extraction(
        self, record: VisionObservationRecord
    ) -> VisionTextExtraction | None:
        reused = self._reuse_terminal(record)
        if reused is None:
            return None
        return VisionTextExtraction(
            visible_text=reused.visible_text,
            measurements=reused.measurements,
            table_rows=reused.table_rows,
            uncertain_content=reused.uncertain_content,
        )

    def _wait_for_extraction(self, record_id: str) -> VisionTextExtraction:
        observation = self._wait_for_result(record_id)
        return VisionTextExtraction(
            visible_text=observation.visible_text,
            measurements=observation.measurements,
            table_rows=observation.table_rows,
            uncertain_content=observation.uncertain_content,
        )

    def _mark_failed(self, record_id: str, error_code: str) -> None:
        self.session.rollback()
        failed = self.session.get(VisionObservationRecord, record_id)
        if failed is None or failed.status == "completed":
            return
        failed.status = "failed"
        failed.quality_status = "failed"
        failed.error_code = error_code[:100]
        failed.completed_at = datetime.now(timezone.utc)
        self.session.commit()

    @staticmethod
    def _observation_fingerprint(observation: VisionObservation) -> str:
        payload = observation.model_dump(mode="json", exclude={"quality_summary"})
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def _stored_fingerprint(cls, payload: dict | None) -> str:
        if not payload:
            return ""
        return cls._observation_fingerprint(VisionObservation.model_validate(payload))
