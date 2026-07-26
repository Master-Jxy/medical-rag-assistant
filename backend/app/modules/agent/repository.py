"""按用户隔离的Agent运行、步骤和产物持久化。"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.modules.agent.models import AgentArtifact, AgentRun, AgentStep
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.state import AgentRunStatus

FORBIDDEN_REASONING_KEYS = {
    "reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "scratchpad",
    "private_thought",
}


class AgentRunNotFoundError(LookupError):
    pass


class AgentStateConflictError(RuntimeError):
    pass


class UnsafeAgentPayloadError(ValueError):
    pass


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in FORBIDDEN_REASONING_KEYS
            or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


class AgentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        *,
        user_id: str,
        task: str,
        policy: AgentPolicy,
        model_name: str | None = None,
        thread_id: str | None = None,
        trigger_message_id: str | None = None,
    ) -> AgentRun:
        if (thread_id is None) != (trigger_message_id is None):
            raise AgentRunNotFoundError()
        if thread_id is not None and trigger_message_id is not None:
            from app.modules.agent.thread_models import AgentMessage, AgentThread

            owned_thread = self.session.scalar(
                select(AgentThread.id).where(
                    AgentThread.id == thread_id,
                    AgentThread.user_id == user_id,
                )
            )
            owned_message = self.session.scalar(
                select(AgentMessage.id).where(
                    AgentMessage.id == trigger_message_id,
                    AgentMessage.thread_id == thread_id,
                    AgentMessage.user_id == user_id,
                    AgentMessage.role == "user",
                )
            )
            if owned_thread is None or owned_message is None:
                raise AgentRunNotFoundError()
        run = AgentRun(
            user_id=user_id,
            thread_id=thread_id,
            trigger_message_id=trigger_message_id,
            task=task.strip(),
            status=AgentRunStatus.PENDING,
            model_name=model_name,
            max_steps=policy.max_steps,
            max_tokens=policy.max_tokens,
            max_estimated_cost_cny=policy.max_estimated_cost_cny,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def link_response_message(
        self,
        user_id: str,
        run_id: str,
        response_message_id: str,
    ) -> AgentRun:
        from app.modules.agent.thread_models import AgentMessage

        run = self.get_run(user_id, run_id)
        message = self.session.scalar(
            select(AgentMessage).where(
                AgentMessage.id == response_message_id,
                AgentMessage.user_id == user_id,
                AgentMessage.thread_id == run.thread_id,
                AgentMessage.role == "assistant",
                AgentMessage.run_id == run.id,
            )
        )
        if message is None:
            raise AgentRunNotFoundError()
        run.response_message_id = message.id
        self.session.flush()
        return run

    def list_runs(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[AgentRun]:
        return list(
            self.session.scalars(
                select(AgentRun)
                .where(AgentRun.user_id == user_id)
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def get_run(
        self,
        user_id: str,
        run_id: str,
        *,
        include_details: bool = False,
    ) -> AgentRun:
        statement = select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
        )
        if include_details:
            statement = statement.options(
                selectinload(AgentRun.steps),
                selectinload(AgentRun.artifacts),
            )
        run = self.session.scalar(statement)
        if run is None:
            raise AgentRunNotFoundError()
        return run

    def start_run(self, user_id: str, run_id: str) -> AgentRun:
        return self._transition(
            user_id,
            run_id,
            expected={AgentRunStatus.PENDING},
            target=AgentRunStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            error_type=None,
        )

    def complete_run(
        self,
        user_id: str,
        run_id: str,
        *,
        final_result: str,
        used_tokens: int,
        estimated_cost_cny: float,
    ) -> AgentRun:
        return self._transition(
            user_id,
            run_id,
            expected={AgentRunStatus.RUNNING},
            target=AgentRunStatus.COMPLETED,
            final_result=final_result,
            used_tokens=used_tokens,
            estimated_cost_cny=estimated_cost_cny,
            error_type=None,
            finished_at=datetime.now(timezone.utc),
        )

    def fail_run(self, user_id: str, run_id: str, error_type: str) -> AgentRun:
        return self._transition(
            user_id,
            run_id,
            expected={AgentRunStatus.PENDING, AgentRunStatus.RUNNING},
            target=AgentRunStatus.FAILED,
            error_type=error_type,
            finished_at=datetime.now(timezone.utc),
        )

    def stop_run(self, user_id: str, run_id: str) -> AgentRun:
        return self._transition(
            user_id,
            run_id,
            expected={AgentRunStatus.PENDING, AgentRunStatus.RUNNING},
            target=AgentRunStatus.STOPPED,
            error_type=None,
            finished_at=datetime.now(timezone.utc),
        )

    def append_step(
        self,
        *,
        user_id: str,
        run_id: str,
        node_name: str,
        tool_name: str | None,
        parameters: dict[str, object],
    ) -> AgentStep:
        if _contains_forbidden_key(parameters):
            raise UnsafeAgentPayloadError("步骤参数不能包含隐藏推理字段")
        run = self._get_run_for_update(user_id, run_id)
        if run.status != AgentRunStatus.RUNNING:
            raise AgentStateConflictError()
        if run.step_count >= run.max_steps:
            raise AgentStateConflictError()
        run.step_count += 1
        step = AgentStep(
            run_id=run.id,
            sequence=run.step_count,
            node_name=node_name,
            tool_name=tool_name,
            parameters=parameters,
            status="running",
        )
        self.session.add(step)
        self.session.flush()
        return step

    def finish_step(
        self,
        *,
        user_id: str,
        step_id: str,
        status: str,
        result_summary: str | None,
        duration_ms: int,
        error_type: str | None = None,
    ) -> AgentStep:
        if status not in {"completed", "failed", "stopped"}:
            raise AgentStateConflictError()
        step = self._get_owned_step(user_id, step_id)
        if step.status != "running":
            raise AgentStateConflictError()
        step.status = status
        step.result_summary = result_summary
        step.duration_ms = duration_ms
        step.error_type = error_type
        step.finished_at = datetime.now(timezone.utc)
        self.session.flush()
        return step

    def add_artifact(
        self,
        *,
        user_id: str,
        run_id: str,
        artifact_type: str,
        file_name: str,
        mime_type: str,
        content: str,
        source_ids: list[str],
    ) -> AgentArtifact:
        run = self.get_run(user_id, run_id)
        if run.status not in {AgentRunStatus.RUNNING, AgentRunStatus.COMPLETED}:
            raise AgentStateConflictError()
        artifact = AgentArtifact(
            run_id=run.id,
            artifact_type=artifact_type,
            file_name=file_name,
            mime_type=mime_type,
            content=content,
            source_ids=source_ids,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def get_artifact(
        self,
        user_id: str,
        artifact_id: str,
    ) -> AgentArtifact:
        artifact = self.session.scalar(
            select(AgentArtifact)
            .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
            .where(
                AgentArtifact.id == artifact_id,
                AgentRun.user_id == user_id,
            )
        )
        if artifact is None:
            raise AgentRunNotFoundError()
        return artifact

    def _transition(
        self,
        user_id: str,
        run_id: str,
        *,
        expected: set[AgentRunStatus],
        target: AgentRunStatus,
        **values: object,
    ) -> AgentRun:
        result = self.session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.user_id == user_id,
                AgentRun.status.in_([status.value for status in expected]),
            )
            .values(status=target.value, **values)
        )
        if result.rowcount != 1:
            if self.session.scalar(
                select(AgentRun.id).where(
                    AgentRun.id == run_id,
                    AgentRun.user_id == user_id,
                )
            ) is None:
                raise AgentRunNotFoundError()
            raise AgentStateConflictError()
        self.session.flush()
        return self.get_run(user_id, run_id)

    def _get_run_for_update(self, user_id: str, run_id: str) -> AgentRun:
        run = self.session.scalar(
            select(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.user_id == user_id)
            .with_for_update()
        )
        if run is None:
            raise AgentRunNotFoundError()
        return run

    def _get_owned_step(self, user_id: str, step_id: str) -> AgentStep:
        step = self.session.scalar(
            select(AgentStep)
            .join(AgentRun, AgentRun.id == AgentStep.run_id)
            .where(AgentStep.id == step_id, AgentRun.user_id == user_id)
        )
        if step is None:
            raise AgentRunNotFoundError()
        return step
