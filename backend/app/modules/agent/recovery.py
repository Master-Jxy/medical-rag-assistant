"""把进程重启前遗留的非终态Agent记录收敛为可解释失败。"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.agent.models import AgentRun, AgentStep
from app.modules.agent.thread_models import AgentMessage


RESTART_ERROR_CODE = "AGENT_PROCESS_RESTARTED"


class AgentRecoveryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def recover_interrupted(self) -> tuple[int, int, int]:
        now = datetime.now(timezone.utc)
        runs = list(
            self.session.scalars(
                select(AgentRun).where(
                    AgentRun.status.in_(("pending", "running"))
                )
            ).all()
        )
        run_ids = {item.id for item in runs}
        for run in runs:
            run.status = "failed"
            run.error_type = RESTART_ERROR_CODE
            run.finished_at = now

        steps = list(
            self.session.scalars(
                select(AgentStep).where(AgentStep.status == "running")
            ).all()
        )
        for step in steps:
            step.status = "failed"
            step.error_type = RESTART_ERROR_CODE
            step.finished_at = now

        messages = list(
            self.session.scalars(
                select(AgentMessage).where(
                    AgentMessage.role == "assistant",
                    AgentMessage.status.in_(("pending", "streaming")),
                )
            ).all()
        )
        for message in messages:
            metadata = dict(message.message_metadata or {})
            metadata["error_code"] = RESTART_ERROR_CODE
            message.status = "failed"
            message.content = (
                message.content or "Agent进程重启，本轮任务已中止，请重试。"
            )
            message.message_metadata = metadata
            message.updated_at = now
            if message.run_id and message.run_id not in run_ids:
                # 消息本身仍是非终态时也必须收敛，避免刷新后永久等待。
                run = self.session.get(AgentRun, message.run_id)
                if run is not None and run.status not in {
                    "completed",
                    "failed",
                    "stopped",
                }:
                    run.status = "failed"
                    run.error_type = RESTART_ERROR_CODE
                    run.finished_at = now
        self.session.commit()
        return len(runs), len(steps), len(messages)
