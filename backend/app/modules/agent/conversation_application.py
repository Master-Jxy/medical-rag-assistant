"""在thread/message之上编排一次受控Agent运行与SSE持久化。"""

import json
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
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
    ) -> None:
        self.session = session
        self.policy = policy
        self.generation_lock = generation_lock
        self.idempotency = idempotency
        self.context_builder = context_builder
        self.threads = AgentThreadRepository(session)
        self.runs = AgentRepository(session)
        self.thread_service = AgentThreadService(session)
        self.memory_extraction = memory_extraction or build_memory_scheduler(session)
        settings = get_settings()
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
    ) -> Iterator[dict[str, object]]:
        if not self.policy.enabled:
            raise AgentDisabledError()
        try:
            thread = self.threads.get_thread(user_id, thread_id)
        except AgentThreadNotFoundError as exc:
            raise AgentThreadNotFoundAppError() from exc
        metadata = {
            "referenced_message_ids": list(payload.referenced_message_ids),
            "source_ids": list(payload.source_ids),
            "artifact_ids": list(payload.artifact_ids),
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
            run = self.runs.create_run(
                user_id=user_id,
                task=payload.content,
                policy=self.policy,
                model_name=self.agent.model_name,
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
            context = self.context_builder.build(
                user_id=user_id,
                thread_id=thread_id,
                current_message=user_message,
            )
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
                        rendered_context=context.rendered,
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
                },
            }
            agent_stream = self.agent.stream_run(
                user_id,
                run.id,
                task_context=context.rendered,
                assistant_mode=thread.assistant_mode,
                resolved_references=context.resolved_references,
                previous_clarification_key=context.previous_clarification_key,
                context_budget=dict(context.section_tokens),
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
        payload = AgentMessageStreamRequest(
            content=original.content,
            referenced_message_ids=[
                original.id,
                *metadata.get("referenced_message_ids", []),
            ],
            source_ids=metadata.get("source_ids", []),
            artifact_ids=metadata.get("artifact_ids", []),
        )
        yield from self.stream_message(
            user_id=user_id,
            thread_id=original.thread_id,
            payload=payload,
            client_request_id=client_request_id,
            request_id=request_id,
            reply_to_message_id=original.id,
        )

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
