"""只清理thread_id为空的旧Agent运行；默认只读预检。"""

import argparse
from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.modules.agent.models import AgentArtifact, AgentRun, AgentStep

CONFIRM_PHRASE = "DELETE_LEGACY_AGENT_RUNS"


@dataclass(frozen=True)
class LegacyRunCleanupReport:
    runs: int
    steps: int
    artifacts: int
    files: int = 0
    deleted: bool = False


def inspect_legacy_runs(session: Session) -> LegacyRunCleanupReport:
    legacy_ids = select(AgentRun.id).where(AgentRun.thread_id.is_(None))
    return LegacyRunCleanupReport(
        runs=session.scalar(
            select(func.count()).select_from(AgentRun).where(
                AgentRun.thread_id.is_(None)
            )
        )
        or 0,
        steps=session.scalar(
            select(func.count()).select_from(AgentStep).where(
                AgentStep.run_id.in_(legacy_ids)
            )
        )
        or 0,
        artifacts=session.scalar(
            select(func.count()).select_from(AgentArtifact).where(
                AgentArtifact.run_id.in_(legacy_ids)
            )
        )
        or 0,
    )


def cleanup_legacy_runs(
    session: Session,
    *,
    confirmation: str | None = None,
) -> LegacyRunCleanupReport:
    report = inspect_legacy_runs(session)
    if confirmation != CONFIRM_PHRASE:
        return report
    legacy_ids = list(
        session.scalars(
            select(AgentRun.id).where(AgentRun.thread_id.is_(None))
        ).all()
    )
    if legacy_ids:
        session.execute(
            delete(AgentArtifact).where(AgentArtifact.run_id.in_(legacy_ids))
        )
        session.execute(
            delete(AgentStep).where(AgentStep.run_id.in_(legacy_ids))
        )
        session.execute(
            delete(AgentRun).where(
                AgentRun.id.in_(legacy_ids),
                AgentRun.thread_id.is_(None),
            )
        )
    session.commit()
    return LegacyRunCleanupReport(
        **{**asdict(report), "deleted": True}
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm",
        help=f"真正删除时必须精确传入 {CONFIRM_PHRASE}",
    )
    args = parser.parse_args()
    session = get_session_factory()()
    try:
        print(
            asdict(
                cleanup_legacy_runs(
                    session,
                    confirmation=args.confirm,
                )
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
