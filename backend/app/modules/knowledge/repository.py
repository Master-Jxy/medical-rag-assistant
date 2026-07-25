"""知识库文档登记的 MySQL 查询与持久化。"""

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.knowledge.models import KnowledgeDocument, KnowledgeSubmission

MYSQL_LOCK_ERROR_CODES = {1205, 1213, 3572}


class DocumentLockConflictError(RuntimeError):
    pass


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, document_id: str) -> KnowledgeDocument | None:
        return self.session.get(KnowledgeDocument, document_id)

    def get_by_id_for_update(self, document_id: str) -> KnowledgeDocument | None:
        try:
            return self.session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == document_id)
                .with_for_update(nowait=True)
            )
        except OperationalError as exc:
            error_code = exc.orig.args[0] if getattr(exc.orig, "args", ()) else None
            if error_code in MYSQL_LOCK_ERROR_CODES:
                raise DocumentLockConflictError() from exc
            raise

    def get_by_hash(self, content_hash: str) -> KnowledgeDocument | None:
        return self.session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.content_hash == content_hash
            )
        )

    def list_all(self) -> list[KnowledgeDocument]:
        return self.session.scalars(
            select(KnowledgeDocument).order_by(
                KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc()
            )
        ).all()

    def list_by_uploader(self, uploader_id: str) -> list[KnowledgeDocument]:
        return self.session.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.uploader_id == uploader_id)
            .order_by(
                KnowledgeDocument.created_at.desc(),
                KnowledgeDocument.id.desc(),
            )
        ).all()

    def count_by_uploader(self, uploader_id: str) -> int:
        return self.session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.uploader_id == uploader_id)
        ) or 0

    def count(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(KnowledgeDocument)
        ) or 0

    def add(self, document: KnowledgeDocument) -> None:
        self.session.add(document)

    def delete(self, document: KnowledgeDocument) -> None:
        self.session.delete(document)


class SubmissionReviewRepository:
    """审核状态的原子迁移；状态条件是并发操作的唯一裁决依据。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, submission_id: str) -> KnowledgeSubmission | None:
        return self.session.get(KnowledgeSubmission, submission_id)

    def claim_for_indexing(self, submission_id: str, expected_status: str) -> bool:
        result = self.session.execute(
            update(KnowledgeSubmission)
            .where(
                KnowledgeSubmission.id == submission_id,
                KnowledgeSubmission.status == expected_status,
            )
            .values(
                status="indexing",
                rejection_reason=None,
                failure_reason=None,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def reject_pending(self, submission_id: str, reason: str) -> bool:
        result = self.session.execute(
            update(KnowledgeSubmission)
            .where(
                KnowledgeSubmission.id == submission_id,
                KnowledgeSubmission.status == "pending_review",
            )
            .values(status="rejected", rejection_reason=reason)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1
