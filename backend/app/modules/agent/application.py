"""Agent运行创建、查询、停止、图执行和持久化编排。"""

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
    ) -> None:
        self.session = session
        self.policy = policy
        self.graph_factory = graph_factory
        self.cancellation = cancellation
        self.model_name = model_name
        self.telemetry = telemetry or NullTelemetry()
        self.repository = AgentRepository(session)

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
                    yield {
                        "event": "tool_started",
                        "data": {
                            "tool_name": current.get("selected_tool"),
                            "step": current["step_count"] + 1,
                        },
                    }
                elif node == AgentNode.EXECUTE_TOOL:
                    self._persist_tool_step(
                        user_id,
                        run_id,
                        current,
                        round((monotonic() - tool_started_at) * 1000),
                    )
                    result = current.get("last_tool_result")
                    yield {
                        "event": "tool_completed",
                        "data": {
                            "tool_name": current.get("selected_tool"),
                            "summary": (
                                result.get("summary") if isinstance(result, dict) else None
                            ),
                            "status": (
                                "failed" if current.get("error_type") else "completed"
                            ),
                        },
                    }
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
            yield from self._finish_run(user_id, run_id, final_state)
        except GeneratorExit:
            self.cancellation.request_stop(user_id, run_id)
            self._safe_stop(user_id, run_id)
            raise
        except Exception:
            self.session.rollback()
            self._safe_fail(user_id, run_id, "AGENT_EXECUTION_FAILED")
            yield {
                "event": "error",
                "data": {
                    "code": "AGENT_EXECUTION_FAILED",
                    "message": "Agent运行失败，请稍后重试",
                },
            }
        finally:
            self.cancellation.clear(user_id, run_id)

    def _persist_tool_step(
        self,
        user_id: str,
        run_id: str,
        state,
        duration_ms: int,
    ) -> None:
        step = self.repository.append_step(
            user_id=user_id,
            run_id=run_id,
            node_name=AgentNode.EXECUTE_TOOL,
            tool_name=state.get("selected_tool"),
            parameters=state.get("tool_arguments", {}),
        )
        result = state.get("last_tool_result")
        self.repository.finish_step(
            user_id=user_id,
            step_id=step.id,
            status="failed" if state.get("error_type") else "completed",
            result_summary=(
                result.get("summary") if isinstance(result, dict) else None
            ),
            duration_ms=duration_ms,
            error_type=state.get("error_type"),
        )
        self.session.commit()

    def _finish_run(self, user_id: str, run_id: str, state):
        status = state["status"]
        if status == AgentRunStatus.COMPLETED:
            output = state.get("final_output") or "任务已完成。"
            self.repository.complete_run(
                user_id,
                run_id,
                final_result=output,
                used_tokens=state["used_tokens"],
                estimated_cost_cny=state["estimated_cost_cny"],
            )
            self.session.commit()
            yield {"event": "token", "data": {"content": output}}
            self._emit("agent_run", user_id, run_id, "success")
            yield {
                "event": "run_completed",
                "data": {
                    "run_id": run_id,
                    "used_tokens": state["used_tokens"],
                    "estimated_cost_cny": state["estimated_cost_cny"],
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
