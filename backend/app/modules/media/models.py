"""Persistence models for private chat media and message bindings."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint("status IN ('uploaded','attached','deleted','expired','failed')", name="ck_media_assets_status"),
        CheckConstraint("byte_size > 0 AND width > 0 AND height > 0", name="ck_media_assets_dimensions"),
        Index("ix_media_assets_user_status_expires", "user_id", "status", "expires_at"),
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    media_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    surface: Mapped[str] = mapped_column(String(20), nullable=False)
    conversation_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    agent_message_id: Mapped[str | None] = mapped_column(ForeignKey("agent_messages.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("surface IN ('rag','agent')", name="ck_message_attachments_surface"),
        CheckConstraint("(surface = 'rag' AND conversation_message_id IS NOT NULL AND agent_message_id IS NULL) OR (surface = 'agent' AND agent_message_id IS NOT NULL AND conversation_message_id IS NULL)", name="ck_message_attachments_target"),
        UniqueConstraint("media_asset_id", name="uq_message_attachments_asset"),
        UniqueConstraint("conversation_message_id", "position", name="uq_message_attachments_rag_position"),
        UniqueConstraint("agent_message_id", "position", name="uq_message_attachments_agent_position"),
    )
