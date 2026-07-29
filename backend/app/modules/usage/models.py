"""不含业务正文的模型用量账本模型。"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ModelUsageRecord(Base):
    __tablename__ = "model_usage_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    call_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    token_measurement: Mapped[str] = mapped_column(String(20), nullable=False)
    input_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    output_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    estimated_cost_cny: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "token_measurement IN ('actual','unknown','not_applicable')",
            name="ck_model_usage_records_measurement",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_model_usage_records_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_model_usage_records_output_tokens",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_model_usage_records_total_tokens",
        ),
        Index("ix_model_usage_records_surface_created", "surface", "created_at"),
    )
