"""Agent运行创建、查询、停止、图执行和持久化编排。"""

import logging
from collections.abc import Callable, Iterator
from time import monotonic

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AgentDisabledError,
    AgentRunConflictError,
    AgentRunNotFoundAppError,
)
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.contracts import AgentToolResult
from app.modules.agent.graph import BoundedAgentGraph
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.repository import (
    AgentRepository,
    AgentRunNotFoundError,
    AgentStateConflictError,
)
from app.modules.agent.schemas import (
    AgentRunListResponse,
    AgentRunResponse,
    AgentStopResponse,
)
from app.modules.agent.state import AgentNode, AgentRunStatus, create_initial_state
from app.ports.telemetry import (
    NullTelemetry,
    TelemetryEvent,
    TelemetryPort,
    emit_safely,
)
from app.core.config import get_settings
from app.core.request_context import get_request_id
from app.modules.rag.ports import ModelUsage, TokenMeasurement
from app.modules.usage.service import ModelUsageRecorder

logger = logging.getLogger(__name__)

AgentGraphFactory = Callable[[str, str], BoundedAgentGraph]


class AgentApplicationService:
    def __init__(
        self,
        session: Session,
        *,
        policy: AgentPolicy,
        graph_factory: AgentGraphFactory,
        cancellation: AgentCancellationService,
        model_name: str | None = None,
        telemetry: TelemetryPort | None = None,
        usage_recorder: ModelUsageRecorder | None = None,
        input_price_per_million_tokens_cny: float | None = None,
        output_price_per_million_tokens_cny: float | None = None,
    ) -> None:
        self.session = session
        self.policy = policy
        self.graph_factory = graph_factory
        self.cancellation = cancellation
        self.model_name = model_name
        self.telemetry = telemetry or NullTelemetry()
        self.repository = AgentRepository(session)
        settings = get_settings()
        self.usage_recorder = usage_recorder or ModelUsageRecorder(session)
        self.input_price = (
            settings.agent_input_price_per_million_tokens_cny
            if input_price_per_million_tokens_cny is None
            else input_price_per_million_tokens_cny
        )
        self.output_price = (
            settings.agent_output_price_per_million_tokens_cny
            if output_price_per_million_tokens_cny is None
            else output_price_per_million_tokens_cny
        )
        self._usage_finalized: set[str] = set()

    def create_run(self, user_id: str, task: str) -> AgentRunResponse:
        if not self.policy.enabled:
            raise AgentDisabledError()
        run = self.repository.create_run(
            user_id=user_id,
            task=task,
            policy=self.policy,
            model_name=self.model_name,
        )
        self.session.commit()
        return AgentRunResponse.model_validate(run)

    def list_runs(
        self, user_id: str, *, offset: int, limit: int
    ) -> AgentRunListResponse:
        runs = self.repository.list_runs(user_id, offset=offset, limit=limit)
        return AgentRunListResponse(
            items=[AgentRunResponse.model_validate(run) for run in runs],
            offset=offset,
            limit=limit,
        )

    def get_run(self, user_id: str, run_id: str) -> AgentRunResponse:
        try:
            run = self.repository.get_run(user_id, run_id, include_details=True)
        except AgentRunNotFoundError as exc:
            raise AgentRunNotFoundAppError() from exc
        return AgentRunResponse.model_validate(run)

    def stop_run(self, user_id: str, run_id: str) -> AgentStopResponse:
        try:
            run = self.repository.get_run(user_id, run_id)
            if run.status == AgentRunStatus.PENDING:
                self.repository.stop_run(user_id, run_id)
                self.session.commit()
                return AgentStopResponse(status="stopped", message="运行已停止")
            if run.status == AgentRunStatus.RUNNING:
                self.cancellation.request_stop(user_id, run_id)
                return AgentStopResponse(status="stopping", message="正在安全停止")
            return AgentStopResponse(status=run.status, message="运行已经结束")
        except AgentRunNotFoundError as exc:
            raise AgentRunNotFoundAppError() from exc

    def get_artifact(self, user_id: str, artifact_id: str):
        try:
            return self.repository.get_artifact(user_id, artifact_id)
        except AgentRunNotFoundError as exc:
            raise AgentRunNotFoundAppError() from exc

    def stream_run(
        self,
        user_id: str,
        run_id: str,
        *,
        task_context: str | None = None,
    ) -> Iterator[dict[str, object]]:
        try:
            run = self.repository.get_run(user_id, run_id)
            self.repository.start_run(user_id, run_id)
            self.session.commit()
        except AgentRunNotFoundError as exc:
            raise AgentRunNotFoundAppError() from exc
        except AgentStateConflictError as exc:
            raise AgentRunConflictError() from exc

        yield {"event": "run_started", "data": {"run_id": run_id}}
        self._emit("agent_run", user_id, run_id, "started")
        state = create_initial_state(
            run_id=run_id,
            user_id=user_id,
            task=task_context or run.task,
            policy=self.policy,
        )
        graph = self.graph_factory(user_id, run_id)
        tool_started_at = monotonic()
        active_step = None
        last_node = None
        final_state = state
        try:
            for current in graph.stream_values(state):
                final_state = current
                node = current["current_node"]
                if node == AgentNode.CLASSIFY_AND_PLAN and not current["plan"]:
                    # LangGraph values模式首先回放输入状态，不把它当成节点完成事件。
                    continue
                if node == last_node:
                    continue
                last_node = node
                if node == AgentNode.CLASSIFY_AND_PLAN and current["plan"]:
                    yield {
                        "event": "plan_ready",
                        "data": {"plan": current["plan"]},
                    }
                elif node == AgentNode.SELECT_TOOL:
                    tool_started_at = monotonic()
                    active_step = self.repository.append_step(
                        user_id=user_id,
                        run_id=run_id,
                        node_name=AgentNode.EXECUTE_TOOL,
                        tool_name=current.get("selected_tool"),
                        parameters=current.get("tool_arguments", {}),
                    )
                    self.session.commit()
                    yield {
                        "event": "tool_started",
                        "data": {
                            "step_id": active_step.id,
                            "tool_name": current.get("selected_tool"),
                            "step": active_step.sequence,
                        },
                    }
                elif node == AgentNode.EXECUTE_TOOL:
                    result = current.get("last_tool_result")
                    if active_step is not None:
                        self.repository.finish_step(
                            user_id=user_id,
                            step_id=active_step.id,
                            status=(
                                "failed"
                                if current.get("error_type")
                                else "completed"
                            ),
                            result_summary=(
                                result.get("summary")
                                if isinstance(result, dict)
                                else None
                            ),
                            duration_ms=round(
                                (monotonic() - tool_started_at) * 1000
                            ),
                            error_type=current.get("error_type"),
                        )
                        self.session.commit()
                    yield {
                        "event": "tool_completed",
                        "data": {
                            "step_id": active_step.id if active_step else None,
                            "tool_name": current.get("selected_tool"),
                            "summary": (
                                result.get("summary") if isinstance(result, dict) else None
                            ),
                            "status": (
                                "failed" if current.get("error_type") else "completed"
                            ),
                        },
                    }
                    active_step = None
                    self._emit(
                        "agent_tool",
                        user_id,
                        run_id,
                        "failure" if current.get("error_type") else "success",
                        error_type=current.get("error_type"),
                    )
                    if isinstance(result, dict):
                        source_ids = [
                            str(item) for item in result.get("source_ids", [])
                        ]
                        if source_ids:
                            source_items = []
                            data = result.get("data")
                            if isinstance(data, dict):
                                for item in data.get("items", []):
                                    if isinstance(item, dict):
                                        source_items.append(
                                            {
                                                "document_id": item.get(
                                                    "document_id"
                                                ),
                                                "chunk_id": item.get("chunk_id"),
                                                "file_name": item.get("file_name"),
                                                "page": item.get("page"),
                                            }
                                        )
                            yield {
                                "event": "sources",
                                "data": {
                                    "source_ids": source_ids,
                                    "items": source_items,
                                },
                            }
                        for artifact in result.get("artifacts", []):
                            stored = self.repository.add_artifact(
                                user_id=user_id,
                                run_id=run_id,
                                artifact_type=artifact["artifact_type"],
                                file_name=artifact["file_name"],
                                mime_type=artifact["mime_type"],
                                content=artifact["content"],
                                source_ids=artifact.get("source_ids", []),
                            )
                            self.session.commit()
                            yield {
                                "event": "artifact_ready",
                                "data": {
                                    "artifact_id": stored.id,
                                    "file_name": stored.file_name,
                                    "mime_type": stored.mime_type,
                                },
                            }
                elif node == AgentNode.INSPECT_RESULT:
                    action = str(current.get("next_action") or "finalize")
                    summaries = {
                        "continue": "当前结果还不足以完成任务，继续选择下一项工具。",
                        "finalize": "现有结果足以完成任务，正在组织最终回答。",
                        "fail": "工具结果不可用，任务将安全结束。",
                    }
                    yield {
                        "event": "decision",
                        "data": {
                            "action": action,
                            "summary": summaries.get(
                                action,
                                "已检查工具结果，正在确定下一步。",
                            ),
                        },
                    }
            if active_step is not None:
                step_status = (
                    "stopped"
                    if final_state["status"] == AgentRunStatus.STOPPED
                    else "failed"
                )
                self.repository.finish_step(
                    user_id=user_id,
                    step_id=active_step.id,
                    status=step_status,
                    duration_ms=round((monotonic() - tool_started_at) * 1000),
                    error_type=final_state.get("error_type")
                    or final_state.get("stop_reason"),
                )
                self.session.commit()
                yield {
                    "event": "tool_completed",
                    "data": {
                        "step_id": active_step.id,
                        "tool_name": final_state.get("selected_tool"),
                        "summary": None,
                        "status": step_status,
                    },
                }
                active_step = None
            yield from self._finish_run(
                user_id,
                run_id,
                final_state,
                graph=graph,
            )
        except GeneratorExit:
            self.cancellation.request_stop(user_id, run_id)
            if active_step is not None:
                self.repository.finish_step(
                    user_id=user_id,
                    step_id=active_step.id,
                    status="stopped",
                    duration_ms=round((monotonic() - tool_started_at) * 1000),
                    error_type="client_disconnected",
                )
                self.session.commit()
            self._safe_stop(user_id, run_id)
            raise
        except Exception:
            self.session.rollback()
            if active_step is not None:
                self.repository.finish_step(
                    user_id=user_id,
                    step_id=active_step.id,
                    status="failed",
                    duration_ms=round((monotonic() - tool_started_at) * 1000),
                    error_type="AGENT_EXECUTION_FAILED",
                )
                self.session.commit()
            self._safe_fail(user_id, run_id, "AGENT_EXECUTION_FAILED")
            yield {
                "event": "error",
                "data": {
                    "code": "AGENT_EXECUTION_FAILED",
                    "message": "Agent运行失败，请稍后重试",
                },
            }
        finally:
            if run_id not in self._usage_finalized:
                self._persist_model_usage(
                    user_id,
                    run_id,
                    graph,
                    int(final_state.get("used_tokens", 0)),
                )
            self.cancellation.clear(user_id, run_id)

    def _finish_run(self, user_id: str, run_id: str, state, *, graph=None):
        status = state["status"]
        if status == AgentRunStatus.COMPLETED:
            output = state.get("final_output")
            used_tokens = state["used_tokens"]
            estimated_cost_cny = state["estimated_cost_cny"]
            if not output and graph is not None:
                answer_stream = graph.stream_final_answer(state)
                if answer_stream is not None:
                    output_parts = []
                    for chunk in answer_stream:
                        if self.cancellation.is_requested(user_id, run_id):
                            close_stream = getattr(answer_stream, "close", None)
                            if callable(close_stream):
                                close_stream()
                            self._safe_stop(user_id, run_id)
                            self._emit(
                                "agent_stop",
                                user_id,
                                run_id,
                                "stopped",
                                error_type="user_requested",
                            )
                            yield {
                                "event": "stopped",
                                "data": {
                                    "run_id": run_id,
                                    "reason": "user_requested",
                                },
                            }
                            return
                        if chunk.content:
                            output_parts.append(chunk.content)
                            yield {
                                "event": "token",
                                "data": {"content": chunk.content},
                            }
                        used_tokens += chunk.used_tokens
                        estimated_cost_cny += chunk.estimated_cost_cny
                        budget_reason = None
                        if used_tokens > state["max_tokens"]:
                            budget_reason = "token_budget"
                        elif (
                            estimated_cost_cny
                            > state["max_estimated_cost_cny"]
                        ):
                            budget_reason = "cost_budget"
                        if budget_reason:
                            close_stream = getattr(answer_stream, "close", None)
                            if callable(close_stream):
                                close_stream()
                            self._safe_stop(user_id, run_id)
                            self._emit(
                                "agent_stop",
                                user_id,
                                run_id,
                                "stopped",
                                error_type=budget_reason,
                            )
                            yield {
                                "event": "stopped",
                                "data": {
                                    "run_id": run_id,
                                    "reason": budget_reason,
                                },
                            }
                            return
                    output = "".join(output_parts)
            output = output or "任务已完成。"
            token_measurement = self._persist_model_usage(
                user_id,
                run_id,
                graph,
                used_tokens,
            )
            self.repository.complete_run(
                user_id,
                run_id,
                final_result=output,
                used_tokens=used_tokens,
                estimated_cost_cny=estimated_cost_cny,
                token_measurement=token_measurement,
            )
            self.session.commit()
            if state.get("final_output"):
                yield {"event": "token", "data": {"content": output}}
            self._emit("agent_run", user_id, run_id, "success")
            yield {
                "event": "run_completed",
                "data": {
                    "run_id": run_id,
                    "used_tokens": used_tokens,
                    "estimated_cost_cny": estimated_cost_cny,
                },
            }
        elif status == AgentRunStatus.STOPPED:
            self._safe_stop(user_id, run_id)
            self._emit(
                "agent_stop",
                user_id,
                run_id,
                "stopped",
                error_type=str(state.get("stop_reason") or "user_requested"),
            )
            yield {
                "event": "stopped",
                "data": {
                    "run_id": run_id,
                    "reason": str(state.get("stop_reason") or "user_requested"),
                },
            }
        else:
            error_type = state.get("error_type") or "AGENT_EXECUTION_FAILED"
            self._safe_fail(user_id, run_id, error_type)
            self._emit(
                "agent_run",
                user_id,
                run_id,
                "failure",
                error_type=error_type,
            )
            yield {
                "event": "error",
                "data": {
                    "code": error_type,
                    "message": "Agent未能完成任务",
                },
            }

    def _persist_model_usage(
        self,
        user_id: str,
        run_id: str,
        graph,
        used_tokens: int,
    ) -> str:
        if run_id in self._usage_finalized:
            run = self.repository.get_run(user_id, run_id)
            return run.token_measurement
        drain = getattr(graph, "drain_model_usage", None)
        observations = list(drain()) if callable(drain) else []
        if not observations:
            fallback = (
                ModelUsage.unknown()
                if used_tokens > 0
                else ModelUsage.not_applicable()
            )
            operation = (
                "legacy_unknown"
                if fallback.measurement is TokenMeasurement.UNKNOWN
                else "not_applicable"
            )
            recorded = self._record_model_usage_safely(
                call_id=f"agent:{run_id}:{operation}:0",
                request_id=get_request_id(),
                user_id=user_id,
                surface="agent",
                operation=operation,
                model_name=self.model_name or "unknown",
                usage=fallback,
                input_price_per_million_tokens_cny=self.input_price,
                output_price_per_million_tokens_cny=self.output_price,
            )
            measurement = (
                fallback.measurement.value
                if recorded
                else TokenMeasurement.UNKNOWN.value
            )
        else:
            measurements = []
            for observation in observations:
                recorded = self._record_model_usage_safely(
                    call_id=(
                        f"agent:{run_id}:{observation.operation}:"
                        f"{observation.sequence}"
                    ),
                    request_id=get_request_id(),
                    user_id=user_id,
                    surface="agent",
                    operation=observation.operation,
                    model_name=self.model_name or "unknown",
                    usage=observation.usage,
                    input_price_per_million_tokens_cny=self.input_price,
                    output_price_per_million_tokens_cny=self.output_price,
                )
                measurements.append(
                    observation.usage.measurement
                    if recorded
                    else TokenMeasurement.UNKNOWN
                )
            measurement = (
                TokenMeasurement.UNKNOWN.value
                if TokenMeasurement.UNKNOWN in measurements
                else TokenMeasurement.ACTUAL.value
            )
        self.repository.set_token_measurement(user_id, run_id, measurement)
        self.session.commit()
        self._usage_finalized.add(run_id)
        return measurement

    def _record_model_usage_safely(self, **fields) -> bool:
        try:
            self.usage_recorder.record(**fields)
        except Exception as exc:
            self.session.rollback()
            logger.warning(
                "model_usage_record_failed surface=agent error_type=%s",
                type(exc).__name__,
            )
            return False
        return True

    def _safe_stop(self, user_id: str, run_id: str) -> None:
        try:
            self.repository.stop_run(user_id, run_id)
            self.session.commit()
        except AgentStateConflictError:
            self.session.rollback()

    def _safe_fail(self, user_id: str, run_id: str, error_type: str) -> None:
        try:
            self.repository.fail_run(user_id, run_id, error_type)
            self.session.commit()
        except AgentStateConflictError:
            self.session.rollback()

    def _emit(
        self,
        event_name: str,
        user_id: str,
        run_id: str,
        result: str,
        *,
        error_type: str | None = None,
    ) -> None:
        emit_safely(
            self.telemetry,
            TelemetryEvent.create(
                request_id=run_id,
                event_name=event_name,
                result=result,
                route="/api/v1/agent",
                user_id=user_id,
                error_type=error_type,
                model_name=self.model_name,
            ),
        )
