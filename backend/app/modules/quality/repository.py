"""回答质量反馈Repository。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.quality.models import AnswerFeedback


class QualityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_message(self, message_id: str) -> AnswerFeedback | None:
        return self.session.scalar(
            select(AnswerFeedback).where(AnswerFeedback.message_id == message_id)
        )

    def get_owned(self, user_id: str, message_id: str) -> AnswerFeedback | None:
        return self.session.scalar(
            select(AnswerFeedback).where(
                AnswerFeedback.message_id == message_id,
                AnswerFeedback.user_id == user_id,
            )
        )

    def get(self, feedback_id: str) -> AnswerFeedback | None:
        return self.session.get(AnswerFeedback, feedback_id)

    def list_pending(self, offset: int, limit: int):
        condition = AnswerFeedback.review_status == "pending"
        total = self.session.scalar(
            select(func.count()).select_from(AnswerFeedback).where(condition)
        ) or 0
        items = list(
            self.session.scalars(
                select(AnswerFeedback)
                .where(condition)
                .order_by(AnswerFeedback.created_at, AnswerFeedback.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return items, total

    def overview(self) -> dict[str, object]:
        total, positive, negative, pending = self.session.execute(
            select(
                func.count(),
                func.sum(case((AnswerFeedback.rating == "up", 1), else_=0)),
                func.sum(case((AnswerFeedback.rating == "down", 1), else_=0)),
                func.sum(
                    case((AnswerFeedback.review_status == "pending", 1), else_=0)
                ),
            ).select_from(AnswerFeedback)
        ).one()
        issue_rows = self.session.execute(
            select(AnswerFeedback.issue_category, func.count())
            .where(AnswerFeedback.issue_category.is_not(None))
            .group_by(AnswerFeedback.issue_category)
        ).all()
        question_rows = self.session.execute(
            select(AnswerFeedback.question_category, func.count()).group_by(
                AnswerFeedback.question_category
            )
        ).all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=13)
        day = func.date(AnswerFeedback.created_at)
        daily_rows = self.session.execute(
            select(
                day,
                func.count(),
                func.sum(case((AnswerFeedback.rating == "up", 1), else_=0)),
                func.sum(case((AnswerFeedback.rating == "down", 1), else_=0)),
            )
            .where(AnswerFeedback.created_at >= cutoff)
            .group_by(day)
            .order_by(day)
        ).all()
        return {
            "total": int(total or 0),
            "positive": int(positive or 0),
            "negative": int(negative or 0),
            "pending_review": int(pending or 0),
            "issue_counts": {str(key): count for key, count in issue_rows},
            "question_counts": {str(key): count for key, count in question_rows},
            "daily_counts": [
                {
                    "date": str(date),
                    "total": int(day_total or 0),
                    "positive": int(day_positive or 0),
                    "negative": int(day_negative or 0),
                }
                for date, day_total, day_positive, day_negative in daily_rows
            ],
        }

    def mark_reviewed(
        self,
        feedback: AnswerFeedback,
        *,
        status: str,
        reviewer_id: str,
        note: str,
    ) -> None:
        feedback.review_status = status
        feedback.reviewer_id = reviewer_id
        feedback.review_note = note
        feedback.reviewed_at = datetime.now(timezone.utc)
        self.session.flush()
