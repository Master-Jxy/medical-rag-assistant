"""回答反馈与人工复核持久化模型。"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    question_category: Mapped[str] = mapped_column(String(30), nullable=False)
    issue_category: Mapped[str | None] = mapped_column(String(30))
    comment: Mapped[str | None] = mapped_column(String(500))
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("rating IN ('up','down')", name="ck_feedback_rating"),
        CheckConstraint(
            "question_category IN ('symptom','medication','test','emergency',"
            "'prevention','general')",
            name="ck_feedback_question_category",
        ),
        CheckConstraint(
            "issue_category IS NULL OR issue_category IN "
            "('inaccurate','irrelevant','incomplete','unsafe','citation','other')",
            name="ck_feedback_issue_category",
        ),
        CheckConstraint(
            "review_status IN ('pending','resolved','dismissed')",
            name="ck_feedback_review_status",
        ),
        Index("ix_feedback_user_updated", "user_id", "updated_at"),
        Index("ix_feedback_review_created", "review_status", "created_at"),
        Index("ix_feedback_categories", "question_category", "issue_category"),
    )
