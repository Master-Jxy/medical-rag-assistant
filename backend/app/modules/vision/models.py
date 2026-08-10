"""Private structured vision observation persistence."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VisionObservationRecord(Base):
    __tablename__ = "vision_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    assistant_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    observation_scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    focus_instruction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    route_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    quality_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_json: Mapped[dict | None] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        CheckConstraint("kind IN ('overview','focused','report_extract')", name="ck_vision_observations_kind"),
        CheckConstraint("status IN ('pending','completed','failed','stopped')", name="ck_vision_observations_status"),
        CheckConstraint("route_kind IN ('pending','legacy','general','document','report')", name="ck_vision_observations_route_kind"),
        CheckConstraint("quality_status IN ('pending','legacy','pass','review','retry','failed')", name="ck_vision_observations_quality_status"),
        CheckConstraint("provider_call_count >= 0 AND provider_call_count <= 1", name="ck_vision_observations_provider_calls"),
        UniqueConstraint("media_asset_id", "observation_scope_id", "kind", "focus_instruction_hash", name="uq_vision_observations_scope"),
        Index("ix_vision_observations_asset_sequence", "media_asset_id", "sequence_no"),
    )
