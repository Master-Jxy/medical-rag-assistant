"""Agent会话与用户可见消息模型。"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentThread(Base):
    __tablename__ = "agent_threads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False, default="新对话"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    summary: Mapped[str | None] = mapped_column(Text)
    summary_until_message_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "agent_messages.id",
            name="fk_agent_threads_summary_message",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    next_message_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1
    )
    last_read_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    assistant_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="general", server_default="general"
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        foreign_keys="AgentMessage.thread_id",
        order_by="AgentMessage.sequence_no",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','archived')",
            name="ck_agent_threads_status",
        ),
        CheckConstraint(
            "assistant_mode IN ('general','patient','clinician','knowledge')",
            name="ck_agent_threads_assistant_mode",
        ),
        Index(
            "ix_agent_threads_user_status_last_message",
            "user_id",
            "status",
            "last_message_at",
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("agent_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="completed"
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "agent_runs.id",
            name="fk_agent_messages_run_id_runs",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    reply_to_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="SET NULL")
    )
    message_metadata: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    thread: Mapped[AgentThread] = relationship(
        back_populates="messages",
        foreign_keys=[thread_id],
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system')",
            name="ck_agent_messages_role",
        ),
        CheckConstraint(
            "status IN ('pending','streaming','completed','failed','stopped')",
            name="ck_agent_messages_status",
        ),
        UniqueConstraint("run_id", name="uq_agent_messages_run_id"),
        UniqueConstraint(
            "thread_id",
            "sequence_no",
            name="uq_agent_messages_thread_sequence",
        ),
        Index(
            "ix_agent_messages_thread_sequence",
            "thread_id",
            "sequence_no",
        ),
        Index(
            "ix_agent_messages_thread_created",
            "thread_id",
            "created_at",
        ),
        Index(
            "ix_agent_messages_user_created",
            "user_id",
            "created_at",
        ),
    )
