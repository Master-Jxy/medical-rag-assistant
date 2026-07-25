"""当前用户“我的资料”只读查询；后续状态表接入时保持API契约。"""

from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.modules.knowledge.models import KnowledgeSubmission
from app.modules.knowledge.schemas import (
    MySubmissionItem,
    MySubmissionListResponse,
)


class MySubmissionQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_user(self, user_id: str) -> MySubmissionListResponse:
        records = self.session.scalars(
            select(KnowledgeSubmission)
            .where(KnowledgeSubmission.submitter_id == user_id)
            .order_by(KnowledgeSubmission.created_at.desc(), KnowledgeSubmission.id.desc())
        ).all()
        return MySubmissionListResponse(
            items=[
                MySubmissionItem(
                    submission_id=record.id,
                    file_name=record.original_name,
                    status=record.status,
                    rejection_reason=record.rejection_reason,
                    failure_reason=record.failure_reason,
                    can_withdraw=record.status in {"pending_parse", "pending_review"},
                    submitted_at=record.created_at,
                    document_id=record.document_id,
                )
                for record in records
            ],
            total=len(records),
        )

    def count_for_user(self, user_id: str) -> int:
        return self.session.scalar(
            select(func.count())
            .select_from(KnowledgeSubmission)
            .where(KnowledgeSubmission.submitter_id == user_id)
        ) or 0
