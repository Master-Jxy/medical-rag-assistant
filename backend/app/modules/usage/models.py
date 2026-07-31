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
    String, Boolean,
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
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
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
    usage_group_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="dashscope")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer)
    quota_billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (
        CheckConstraint("token_measurement IN ('actual','unknown','not_applicable')", name="ck_model_usage_records_measurement"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_model_usage_records_input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_model_usage_records_output_tokens"),
        CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ck_model_usage_records_total_tokens"),
        Index("ix_model_usage_records_surface_created", "surface", "created_at"),
    )


class QuotaPlan(Base):
    __tablename__ = "quota_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    request_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_limit_cny: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class UserQuotaAssignment(Base):
    __tablename__ = "user_quota_assignments"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("quota_plans.id"), nullable=False)
    token_limit_override: Mapped[int | None] = mapped_column(Integer)
    request_limit_override: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class QuotaPeriod(Base):
    __tablename__ = "quota_periods"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    request_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    used_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    __table_args__ = (Index("uq_quota_period_user_range", "user_id", "period_start", "period_end", unique=True),)


class QuotaReservation(Base):
    __tablename__ = "quota_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    quota_period_id: Mapped[str] = mapped_column(ForeignKey("quota_periods.id", ondelete="CASCADE"), nullable=False)
    surface: Mapped[str] = mapped_column(String(20), nullable=False)
    usage_group_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    charged_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
