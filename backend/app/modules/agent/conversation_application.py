"""在thread/message之上编排一次受控Agent运行与SSE持久化。"""

import json
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AgentDisabledError,
    AgentMessageConflictError,
    AgentMessageNotFoundAppError,
    AgentThreadNotFoundAppError,
)
from app.modules.agent.application import (
    AgentApplicationService,
    AgentGraphFactory,
)
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.context_builder import AgentContextBuilder
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.models import AgentRun
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_repository import (
    AgentMessageNotFoundError,
    AgentThreadNotFoundError,
    AgentThreadRepository,
)
from app.modules.agent.thread_models import AgentMessage
from app.modules.agent.thread_schemas import AgentMessageStreamRequest
from app.modules.agent.thread_service import AgentThreadService
from app.ports.telemetry import TelemetryPort
from app.services.generation_lock_service import GenerationLockService
from app.services.idempotency_service import IdempotencyService
from app.services.memory_extraction_runtime import build_memory_scheduler
from app.modules.usage.quota_service import build_quota_gate
from app.modules.usage.query_service import UsageQueryService
from app.modules.usage.estimator import (
    AgentReservationInput,
    ConservativeQuotaReservationEstimator,
    QuotaReservationEstimatorPort,
)
from app.modules.usage.contracts import QuotaPolicyMode
from app.modules.media.service import MediaAssetService
from app.modules.vision.service import VisionChatService
from app.modules.vision.router_service import VisionRouterService
from app.modules.vision.contracts import VisionObservation
from app.modules.vision.models import VisionObservationRecord
from app.core.model_factory import resolve_model_route
from app.modules.model_gateway.contracts import ModelCapability, ModelSurface


class AgentConversationApplication:
    def __init__(
        self,
        session: Session,
        *,
        policy: AgentPolicy,
        graph_factory: AgentGraphFactory,
        cancellation: AgentCancellationService,
        generation_lock: GenerationLockService,
        idempotency: IdempotencyService,
        context_builder: AgentContextBuilder,
        model_name: str | None = None,
        telemetry: TelemetryPort | None = None,
        memory_extraction=None,
        quota_gate=None,
        quota_estimator: QuotaReservationEstimatorPort | None = None,
        media_service: MediaAssetService | None = None,
        vision_service: VisionChatService | None = None,
        vision_router: VisionRouterService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.policy = policy
        self.cancellation = cancellation
        self.generation_lock = generation_lock
        self.idempotency = idempotency
        self.context_builder = context_builder
        self.threads = AgentThreadRepository(session)
        self.runs = AgentRepository(session)
        self.thread_service = AgentThreadService(session)
        self.memory_extraction = memory_extraction or build_memory_scheduler(session)
        settings = settings or get_settings()
        self.settings = settings
        self.media_service = media_service or MediaAssetService(session, settings)
        self.vision_service = vision_service or VisionChatService(session, settings)
        self.vision_router = vision_router or VisionRouterService(
            self.vision_service, settings
        )
        self.quota_gate = quota_gate or build_quota_gate(session, settings)
        self.quota_estimator = (
            quota_estimator or ConservativeQuotaReservationEstimator()
        )
        self.quota_agent_policy_tokens = min(
            settings.quota_agent_reserve_tokens,
            settings.agent_max_tokens,
        )
        self.agent_model_max_output_tokens = settings.agent_model_max_output_tokens
        self.quota_input_price = settings.agent_input_price_per_million_tokens_cny
        self.quota_output_price = settings.agent_output_price_per_million_tokens_cny
        self.usage_query = UsageQueryService(session)
        self.agent = AgentApplicationService(
            session,
            policy=policy,
            graph_factory=graph_factory,
            cancellation=cancellation,
            model_name=model_name,
            telemetry=telemetry,
        )

    def stream_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        payload: AgentMessageStreamRequest,
        client_request_id: str,
        request_id: str,
        reply_to_message_id: str | None = None,
        reused_attachment_ids: list[str] | None = None,
        reused_visual_records: list[VisionObservationRecord] | None = None,
    ) -> Iterator[dict[str, object]]:
        if not self.policy.enabled:
            raise AgentDisabledError()
        try:
            thread = self.threads.get_thread(user_id, thread_id)
        except AgentThreadNotFoundError as exc:
            raise AgentThreadNotFoundAppError() from exc
        effective_attachment_ids = list(
            reused_attachment_ids
            if reused_attachment_ids is not None
            else payload.attachment_ids
        )
        metadata = {
            "referenced_message_ids": list(payload.referenced_message_ids),
            "source_ids": list(payload.source_ids),
            "artifact_ids": list(payload.artifact_ids),
            "attachment_ids": effective_attachment_ids,
            "model_id": payload.model_id,
        }
        reference_fingerprint = json.dumps(metadata, sort_keys=True)
        claim = self.idempotency.begin_agent(
            user_id,
            client_request_id,
            thread_id,
            payload.content,
            reference_fingerprint,
        )
        if claim.completed_record is not None:
            yield from self._replay_completed(
                user_id, thread_id, claim.completed_record
            )
            return

        lease = None
        user_message = None
        assistant_message = None
        run = None
        agent_stream = None
        terminal = False
        output_parts: list[str] = []
        source_ids: list[str] = []
        artifact_ids: list[str] = []
        source_items: list[dict[str, object]] = []
        reservation = None
        quota_finalized = False
        try:
            lease = self.generation_lock.acquire_agent(user_id, thread_id)
            user_sequence, assistant_sequence, turn_id = (
                self.threads.reserve_turn(user_id, thread_id)
            )
            user_message = self.threads.create_message(
                user_id=user_id,
                thread_id=thread_id,
                role="user",
                content=payload.content,
                status="completed",
                reply_to_message_id=reply_to_message_id,
                metadata=metadata,
                sequence_no=user_sequence,
                turn_id=turn_id,
            )
            selected_route = resolve_model_route(
                self.settings,
                surface=ModelSurface.AGENT,
                capabilities=frozenset({ModelCapability.TEXT}),
                model_id=payload.model_id,
            )
            run = self.runs.create_run(
                user_id=user_id,
                task=payload.content or "请分析上传的图片，并在需要时检索知识库。",
                policy=self.policy,
                model_name=selected_route.model_name,
                thread_id=thread_id,
                trigger_message_id=user_message.id,
            )
            assistant_message = self.threads.create_message(
                user_id=user_id,
                thread_id=thread_id,
                role="assistant",
                content="",
                status="pending",
                run_id=run.id,
                reply_to_message_id=user_message.id,
                metadata={},
                sequence_no=assistant_sequence,
                turn_id=turn_id,
            )
            self.runs.link_response_message(
                user_id, run.id, assistant_message.id
            )
            self.session.commit()
            vision_payload: list[dict[str, object]] = []
            assets = []
            if effective_attachment_ids:
                if reused_attachment_ids is None:
                    assets = self.media_service.bind_agent(
                        user_id, effective_attachment_ids, user_message.id
                    )
                else:
                    assets = [
                        self.media_service.owned_asset(user_id, asset_id)
                        for asset_id in effective_attachment_ids
                    ]
            yield {
                "event": "message_created",
                "data": {
                    "thread_id": thread_id,
                    "user_message_id": user_message.id,
                    "assistant_message_id": assistant_message.id,
                    "run_id": run.id,
                    "user_sequence_no": user_message.sequence_no,
                    "assistant_sequence_no": assistant_message.sequence_no,
                    "turn_id": turn_id,
                    "content": user_message.content,
                },
            }
            if assets:
                for asset in assets:
                    if self.cancellation.is_requested(user_id, run.id):
                        saved_run = self.runs.get_run(user_id, run.id)
                        if saved_run.status in {"pending", "running"}:
                            self.runs.stop_run(user_id, run.id)
                        self._complete_message(
                            user_id,
                            thread_id,
                            assistant_message.id,
                            content="Agent已安全停止。",
                            status="stopped",
                            source_ids=[],
                            source_items=[],
                            artifact_ids=[],
                            stop_reason="user_requested",
                        )
                        self.idempotency.complete_agent(
                            claim,
                            request_id=request_id,
                            thread_id=thread_id,
                            user_message_id=user_message.id,
                            assistant_message_id=assistant_message.id,
                        )
                        terminal = True
                        yield {
                            "event": "stopped",
                            "data": {"run_id": run.id, "reason": "user_requested"},
                        }
                        yield {
                            "event": "message_completed",
                            "data": {
                                "message_id": assistant_message.id,
                                "status": "stopped",
                                "run_id": run.id,
                                "sequence_no": assistant_message.sequence_no,
                                "turn_id": assistant_message.turn_id,
                                "usage": self.usage_query.group_summary(
                                    assistant_message.id, user_id
                                ),
                                "quota": self.quota_gate.current(user_id),
                            },
                        }
                        return
                    reusable = [
                        item for item in (reused_visual_records or [])
                        if item.media_asset_id == asset.id
                    ]
                    if reusable:
                        for sequence_no, source in enumerate(reusable, start=1):
                            observation = VisionObservation.model_validate(
                                source.observation_json
                            )
                            self.session.add(VisionObservationRecord(
                                media_asset_id=asset.id,
                                user_id=user_id,
                                run_id=run.id,
                                observation_scope_id=run.id,
                                kind=source.kind,
                                focus_instruction_hash=source.focus_instruction_hash,
                                model_name=source.model_name,
                                status="completed",
                                sequence_no=sequence_no,
                                route_kind=source.route_kind,
                                quality_status=source.quality_status,
                                quality_codes=list(source.quality_codes or []),
                                provider_call_count=0,
                                observation_json=observation.model_dump(mode="json"),
                                completed_at=source.completed_at,
                            ))
                            vision_payload.append({
                                "media_asset_id": asset.id,
                                "observation": observation.model_dump(mode="json"),
                            })
                        self.session.commit()
                        continue
                    observation = self.vision_router.route_overview(
                        user_id=user_id,
                        asset_id=asset.id,
                        user_question=payload.content or "请说明图片中的可见信息",
                        surface="vision_agent",
                        usage_group_id=assistant_message.id,
                        run_id=run.id,
                    )
                    vision_payload.append({
                        "media_asset_id": asset.id,
                        "observation": observation.model_dump(mode="json"),
                    })
            context = self.context_builder.build(
                user_id=user_id,
                thread_id=thread_id,
                current_message=user_message,
            )
            rendered_context = context.rendered
            if vision_payload:
                visible_facts = "\n\n".join(
                    f"图片 {index} 结构化观察（仅为可见事实，不是诊断）：\n"
                    f"{item['observation']}"
                    for index, item in enumerate(vision_payload, start=1)
                )
                rendered_context = f"{rendered_context}\n\n[图片观察]\n{visible_facts}"
            if getattr(
                self.quota_gate,
                "policy_mode",
                QuotaPolicyMode.ENFORCE,
            ) is QuotaPolicyMode.OFF:
                reservation = self.quota_gate.reserve(
                    user_id,
                    "agent",
                    f"agent:{client_request_id}",
                    0,
                    assistant_message.id,
                )
            else:
                estimate = self.quota_estimator.estimate_agent(
                    AgentReservationInput(
                        rendered_context=rendered_context,
                        estimated_context_tokens=context.estimated_tokens,
                        max_output_tokens=self.agent_model_max_output_tokens,
                        policy_token_limit=self.quota_agent_policy_tokens,
                    )
                )
                reservation = self.quota_gate.reserve(
                    user_id,
                    "agent",
                    f"agent:{client_request_id}",
                    estimate.requested_tokens,
                    assistant_message.id,
                    estimated_input_tokens=estimate.estimated_input_tokens,
                    estimated_output_tokens=estimate.estimated_output_tokens,
                    input_price_per_million_tokens_cny=self.quota_input_price,
                    output_price_per_million_tokens_cny=self.quota_output_price,
                )
            if vision_payload:
                yield {
                    "event": "tool_started",
                    "data": {
                        "tool_name": "observe_image", "public_code": "tool_started",
                        "public_summary": "正在观察用户授权图片", "status": "running",
                        "sequence": 0,
                    },
                }
                yield {
                    "event": "tool_completed",
                    "data": {
                        "tool_name": "observe_image", "public_code": "tool_completed",
                        "public_summary": "已完成图片可见事实观察", "status": "completed",
                        "sequence": 0,
                    },
                }
                yield {
                    "event": "vision_observations",
                    "data": {"label": "图片识别结果", "observations": vision_payload},
                }
            agent_stream = self.agent.stream_run(
                user_id,
                run.id,
                task_context=rendered_context,
                assistant_mode=thread.assistant_mode,
                resolved_references=context.resolved_references,
                previous_clarification_key=context.previous_clarification_key,
                context_budget=dict(context.section_tokens),
                visual_observations=vision_payload,
            )
            for item in agent_stream:
                event = str(item["event"])
                data = dict(item["data"])
                if event == "run_started":
                    self.threads.update_message(
                        user_id,
                        thread_id,
                        assistant_message.id,
                        content="",
                        status="streaming",
                        metadata={},
                    )
                    self.session.commit()
                elif event == "token":
                    output_parts.append(str(data.get("content") or ""))
                elif event == "sources":
                    source_ids.extend(
                        str(value) for value in data.get("source_ids", [])
                    )
                    source_items.extend(
                        item
                        for item in data.get("items", [])
                        if isinstance(item, dict)
                    )
                elif event == "artifact_ready":
                    artifact_ids.append(str(data["artifact_id"]))
                elif event == "run_completed":
                    terminal = True
                    self._complete_message(
                        user_id,
                        thread_id,
                        assistant_message.id,
                        content="".join(output_parts) or "任务已完成。",
                        status="completed",
                        source_ids=source_ids,
                        source_items=source_items,
                        artifact_ids=artifact_ids,
                    )
                    usage = self.usage_query.group_usage(assistant_message.id, user_id)
                    if reservation is not None:
                        self.quota_gate.settle(reservation.id, usage)
                        quota_finalized = True
                    data["usage"] = self.usage_query.group_summary(assistant_message.id, user_id)
                    data["quota"] = self.quota_gate.current(user_id)
                elif event == "stopped":
                    terminal = True
                    self._complete_message(
                        user_id,
                        thread_id,
                        assistant_message.id,
                        content="".join(output_parts) or "Agent已安全停止。",
                        status="stopped",
                        source_ids=source_ids,
                        source_items=source_items,
                        artifact_ids=artifact_ids,
                        stop_reason=str(data.get("reason") or "user_requested"),
                    )
                    usage = self.usage_query.group_usage(assistant_message.id, user_id)
                    if reservation is not None:
                        self.quota_gate.settle(reservation.id, usage)
                        quota_finalized = True
                    data["usage"] = self.usage_query.group_summary(assistant_message.id, user_id)
                    data["quota"] = self.quota_gate.current(user_id)
                elif event == "error":
                    terminal = True
                    self._complete_message(
                        user_id,
                        thread_id,
                        assistant_message.id,
                        content="".join(output_parts) or "Agent未能完成任务。",
                        status="failed",
                        source_ids=source_ids,
                        source_items=source_items,
                        artifact_ids=artifact_ids,
                        error_code=str(
                            data.get("code") or "AGENT_EXECUTION_FAILED"
                        ),
                    )
                    usage = self.usage_query.group_usage(assistant_message.id, user_id)
                    if reservation is not None:
                        self.quota_gate.settle(reservation.id, usage)
                        quota_finalized = True
                    data["usage"] = self.usage_query.group_summary(assistant_message.id, user_id)
                    data["quota"] = self.quota_gate.current(user_id)
                yield item
            if not terminal:
                self._complete_message(
                    user_id,
                    thread_id,
                    assistant_message.id,
                    content="".join(output_parts) or "Agent运行已中断。",
                    status="failed",
                    source_ids=source_ids,
                    source_items=source_items,
                    artifact_ids=artifact_ids,
                    error_code="AGENT_STREAM_INTERRUPTED",
                )
                usage = self.usage_query.group_usage(
                    assistant_message.id, user_id
                )
                if reservation is not None:
                    self.quota_gate.settle(reservation.id, usage)
                    quota_finalized = True
            self.idempotency.complete_agent(
                claim,
                request_id=request_id,
                thread_id=thread_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )
            yield {
                "event": "message_completed",
                "data": {
                    "message_id": assistant_message.id,
                    "status": assistant_message.status,
                    "run_id": run.id,
                    "sequence_no": assistant_message.sequence_no,
                    "turn_id": assistant_message.turn_id,
                    "usage": self.usage_query.group_summary(assistant_message.id, user_id),
                    "quota": self.quota_gate.current(user_id),
                },
            }
            try:
                self.thread_service.refresh_summary(user_id, thread_id)
            except Exception:
                self.session.rollback()
        except GeneratorExit:
            if agent_stream is not None:
                agent_stream.close()
            if reservation is not None and assistant_message is not None:
                usage = self.usage_query.group_usage(
                    assistant_message.id, user_id
                )
                self.quota_gate.settle(reservation.id, usage)
                quota_finalized = True
            if assistant_message is not None:
                self._complete_message(
                    user_id,
                    thread_id,
                    assistant_message.id,
                    content="".join(output_parts) or "Agent已安全停止。",
                    status="stopped",
                    source_ids=source_ids,
                    source_items=source_items,
                    artifact_ids=artifact_ids,
                    stop_reason="client_disconnected",
                )
                self.idempotency.complete_agent(
                    claim,
                    request_id=request_id,
                    thread_id=thread_id,
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                )
            else:
                self.idempotency.abandon(claim)
            raise
        except Exception:
            self.session.rollback()
            if assistant_message is None or user_message is None:
                self.idempotency.abandon(claim)
            else:
                try:
                    saved_run = self.runs.get_run(user_id, run.id)
                    if saved_run.status in {"pending", "running"}:
                        self.runs.fail_run(
                            user_id,
                            run.id,
                            "AGENT_CONVERSATION_FAILED",
                        )
                    self._complete_message(
                        user_id,
                        thread_id,
                        assistant_message.id,
                        content=(
                            "".join(output_parts)
                            or "Agent会话运行失败，请重试。"
                        ),
                        status="failed",
                        source_ids=source_ids,
                        source_items=source_items,
                        artifact_ids=artifact_ids,
                        error_code="AGENT_CONVERSATION_FAILED",
                    )
                    self.idempotency.complete_agent(
                        claim,
                        request_id=request_id,
                        thread_id=thread_id,
                        user_message_id=user_message.id,
                        assistant_message_id=assistant_message.id,
                    )
                except Exception:
                    self.session.rollback()
            raise
        finally:
            if reservation is not None and not quota_finalized:
                self.quota_gate.release(reservation.id)
            if agent_stream is not None:
                agent_stream.close()
            if lease is not None:
                self.generation_lock.release(lease)
            if run is not None:
                self.cancellation.clear(user_id, run.id)

    def retry_message(
        self,
        *,
        user_id: str,
        message_id: str,
        client_request_id: str,
        request_id: str,
    ) -> Iterator[dict[str, object]]:
        try:
            original = self.session.get(AgentMessage, message_id)
            if original is None or original.user_id != user_id:
                raise AgentMessageNotFoundError()
            if original.role != "user":
                raise AgentMessageConflictError()
            previous_run = self.session.scalar(
                select(AgentRun).where(
                    AgentRun.trigger_message_id == original.id,
                    AgentRun.user_id == user_id,
                )
            )
            if previous_run is None or previous_run.status not in {
                "failed",
                "stopped",
            }:
                raise AgentMessageConflictError()
        except AgentMessageNotFoundError as exc:
            raise AgentMessageNotFoundAppError() from exc
        metadata = original.message_metadata or {}
        attachment_ids = [
            str(value) for value in metadata.get("attachment_ids", []) if value
        ]
        reused_visual_records = self._reusable_visual_records(
            user_id, attachment_ids
        )
        payload = AgentMessageStreamRequest(
            content=original.content,
            attachment_ids=attachment_ids,
            referenced_message_ids=[
                original.id,
                *metadata.get("referenced_message_ids", []),
            ],
            source_ids=metadata.get("source_ids", []),
            artifact_ids=metadata.get("artifact_ids", []),
            model_id=metadata.get("model_id"),
        )
        yield from self.stream_message(
            user_id=user_id,
            thread_id=original.thread_id,
            payload=payload,
            client_request_id=client_request_id,
            request_id=request_id,
            reply_to_message_id=original.id,
            reused_attachment_ids=attachment_ids,
            reused_visual_records=reused_visual_records,
        )

    def _reusable_visual_records(
        self,
        user_id: str,
        attachment_ids: list[str],
    ) -> list[VisionObservationRecord]:
        if not attachment_ids:
            return []
        rows = list(self.session.scalars(
            select(VisionObservationRecord)
            .where(
                VisionObservationRecord.user_id == user_id,
                VisionObservationRecord.media_asset_id.in_(attachment_ids),
                VisionObservationRecord.status == "completed",
                VisionObservationRecord.kind.in_(("overview", "focused")),
                VisionObservationRecord.observation_json.is_not(None),
            )
            .order_by(VisionObservationRecord.created_at.desc())
        ))
        selected: list[VisionObservationRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            key = (
                row.media_asset_id,
                row.kind,
                row.focus_instruction_hash,
            )
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
        return list(reversed(selected))

    def _complete_message(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
        *,
        content: str,
        status: str,
        source_ids: list[str],
        source_items: list[dict[str, object]],
        artifact_ids: list[str],
        error_code: str | None = None,
        stop_reason: str | None = None,
    ) -> None:
        metadata: dict[str, object] = {
            "source_ids": list(dict.fromkeys(source_ids)),
            "sources": [
                dict(item)
                for index, item in enumerate(source_items)
                if item
                and item
                not in source_items[:index]
            ],
            "artifact_ids": list(dict.fromkeys(artifact_ids)),
        }
        if error_code:
            metadata["error_code"] = error_code
        if stop_reason:
            metadata["stop_reason"] = stop_reason
        self.threads.update_message(
            user_id,
            thread_id,
            message_id,
            content=content,
            status=status,
            metadata=metadata,
        )
        self.session.commit()
        if status in ("completed", "stopped"):
            message = self.threads.get_message(user_id, thread_id, message_id)
            interval = get_settings().memory_extraction_interval_turns * 2
            previous_user = (
                self.threads.get_message(
                    user_id,
                    thread_id,
                    message.reply_to_message_id,
                )
                if message.reply_to_message_id
                else None
            )
            explicit = bool(previous_user and "记住" in previous_user.content)
            if explicit or message.sequence_no % interval == 0:
                try:
                    self.memory_extraction.schedule(
                        user_id,
                        "agent",
                        thread_id,
                        message.sequence_no,
                        trigger="explicit" if explicit else "periodic",
                    )
                except Exception as exc:
                    self.session.rollback()
                    logger.warning(
                        "memory_extraction_schedule_failed surface=agent error_type=%s",
                        type(exc).__name__,
                    )

    def _replay_completed(self, user_id, thread_id, record):
        try:
            user_message = self.threads.get_message(
                user_id, thread_id, record.user_message_id
            )
            assistant_message = self.threads.get_message(
                user_id, thread_id, record.assistant_message_id
            )
        except AgentMessageNotFoundError as exc:
            raise AgentMessageNotFoundAppError() from exc
        yield {
            "event": "message_created",
            "data": {
                "thread_id": thread_id,
                "user_message_id": user_message.id,
                "assistant_message_id": assistant_message.id,
                "run_id": assistant_message.run_id,
                "user_sequence_no": user_message.sequence_no,
                "assistant_sequence_no": assistant_message.sequence_no,
                "turn_id": assistant_message.turn_id,
                "replayed": True,
            },
        }
        if assistant_message.content:
            yield {
                "event": "token",
                "data": {"content": assistant_message.content},
            }
        yield {
            "event": "message_completed",
            "data": {
                "message_id": assistant_message.id,
                "status": assistant_message.status,
                "run_id": assistant_message.run_id,
                "sequence_no": assistant_message.sequence_no,
                "turn_id": assistant_message.turn_id,
                "replayed": True,
            },
        }
