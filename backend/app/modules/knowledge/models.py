"""公共知识库文档登记模型；正文和向量仍分别保存在文件系统与 Chroma。"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.auth.models import User  # noqa: F401  注册 uploader_id 外键目标表。


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeDocument(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    uploader_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        UniqueConstraint("stored_name", name="uq_documents_stored_name"),
        CheckConstraint("size_bytes >= 0", name="ck_documents_size_nonnegative"),
        CheckConstraint("chunk_count > 0", name="ck_documents_chunk_count_positive"),
        CheckConstraint("status IN ('ready')", name="ck_documents_status"),
        CheckConstraint(
            "(is_system = 1 AND uploader_id IS NULL) OR "
            "(is_system = 0 AND uploader_id IS NOT NULL)",
            name="ck_documents_owner_kind",
        ),
        Index("ix_documents_created_at", "created_at"),
        Index("ix_documents_uploader_id", "uploader_id"),
    )
