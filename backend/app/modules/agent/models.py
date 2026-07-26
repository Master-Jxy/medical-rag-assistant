"""Agent运行、步骤和用户可见产物模型。"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_name: Mapped[str | None] = mapped_column(String(100))
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_estimated_cost_cny: Mapped[float] = mapped_column(Float, nullable=False)
    used_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_cny: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    final_result: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentStep.sequence",
    )
    artifacts: Mapped[list["AgentArtifact"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentArtifact.created_at",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','stopped')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "step_count >= 0 AND step_count <= max_steps",
            name="ck_agent_runs_step_count",
        ),
        CheckConstraint(
            "max_steps >= 1 AND max_steps <= 5",
            name="ck_agent_runs_max_steps",
        ),
        CheckConstraint(
            "max_tokens > 0 AND used_tokens >= 0",
            name="ck_agent_runs_tokens",
        ),
        CheckConstraint(
            "max_estimated_cost_cny >= 0 AND estimated_cost_cny >= 0",
            name="ck_agent_runs_cost",
        ),
        Index("ix_agent_runs_user_created", "user_id", "created_at"),
        Index("ix_agent_runs_user_status", "user_id", "status"),
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[AgentRun] = relationship(back_populates="steps")

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed','stopped')",
            name="ck_agent_steps_status",
        ),
        CheckConstraint("sequence > 0", name="ck_agent_steps_sequence"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_steps_duration",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_agent_steps_run_sequence"),
        Index("ix_agent_steps_run_created", "run_id", "created_at"),
    )


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    run: Mapped[AgentRun] = relationship(back_populates="artifacts")

    __table_args__ = (
        Index("ix_agent_artifacts_run_created", "run_id", "created_at"),
    )
