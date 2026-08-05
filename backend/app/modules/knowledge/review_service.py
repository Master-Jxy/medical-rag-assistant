"""管理员审核与发布编排；并发状态由原子迁移裁决。"""

from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, DocumentStoreError
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.jobs.ports import JobPort
from app.modules.knowledge.asset_storage import ControlledDocumentAssetStore
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.models import (
    DocumentVersion,
    KnowledgeDocument,
    KnowledgeSubmission,
)
from app.modules.knowledge.repository import SubmissionReviewRepository
from app.modules.knowledge.review_schemas import (
    ApprovalResponse,
    ReviewItem,
    ReviewListResponse,
)


class ReviewNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("未找到待审核资料", code="REVIEW_NOT_FOUND", status_code=404)


class ReviewStateConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "当前资料状态不允许该审核操作",
            code="REVIEW_STATE_CONFLICT",
            status_code=409,
        )


class KnowledgeReviewService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        lifecycle: DocumentLifecycleService,
        audit: AuditPort,
        jobs: JobPort,
        repository: SubmissionReviewRepository | None = None,
        asset_store: ControlledDocumentAssetStore | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.lifecycle = lifecycle
        self.audit = audit
        self.jobs = jobs
        self.repository = repository or SubmissionReviewRepository(session)
        self.asset_store = asset_store or ControlledDocumentAssetStore(settings)

    def list_reviews(
        self, *, status: str | None, offset: int, limit: int
    ) -> ReviewListResponse:
        statement = select(KnowledgeSubmission)
        count_statement = select(func.count()).select_from(KnowledgeSubmission)
        if status:
            statement = statement.where(KnowledgeSubmission.status == status)
            count_statement = count_statement.where(KnowledgeSubmission.status == status)
        records = self.session.scalars(
            statement.order_by(
                KnowledgeSubmission.created_at.asc(),
                KnowledgeSubmission.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return ReviewListResponse(
            items=[self._to_item(record) for record in records],
            total=self.session.scalar(count_statement) or 0,
            offset=offset,
            limit=limit,
        )

    def get_review(self, submission_id: str) -> ReviewItem:
        return self._to_item(self._get(submission_id))

    def reject(
        self,
        submission_id: str,
        reason: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ApprovalResponse:
        record = self._get(submission_id)
        normalized_reason = reason.strip()
        if not self.repository.reject_pending(submission_id, normalized_reason):
            self.session.rollback()
            raise ReviewStateConflictError()
        self.audit.record(
            AuditRecord(
                actor_user_id=actor_user_id,
                action="knowledge_submission.rejected",
                object_type="knowledge_submission",
                object_id=record.id,
                request_id=request_id,
                details={"reason": normalized_reason},
            )
        )
        self.session.commit()
        self.asset_store.cleanup_submission_assets(record.id)
        self.session.refresh(record)
        return ApprovalResponse(submission=self._to_item(record))

    async def approve(
        self,
        submission_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ApprovalResponse:
        return await self._publish(
            submission_id,
            expected_status="pending_review",
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    async def _publish(
        self,
        submission_id: str,
        *,
        expected_status: str,
        actor_user_id: str,
        request_id: str | None,
    ) -> ApprovalResponse:
        record = self._get(submission_id)
        if not self.repository.claim_for_indexing(submission_id, expected_status):
            self.session.rollback()
            raise ReviewStateConflictError()
        job = self.jobs.start(
            job_type="publish_submission",
            object_type="knowledge_submission",
            object_id=record.id,
            initial_progress=10,
        )
        self.session.commit()

        document: KnowledgeDocument | None = None
        isolated_path = self.settings.submission_dir / record.stored_name
        try:
            if not isolated_path.is_file():
                raise DocumentStoreError()
            with isolated_path.open("rb") as source:
                upload = UploadFile(filename=record.original_name, file=source)
                document = await self.lifecycle.create_document(
                    upload,
                    uploader_id=record.submitter_id,
                    is_system=False,
                )
            self.asset_store.promote_submission_assets(record.id, document.id)
            record = self._get(submission_id)
            record.status = "published"
            record.document_id = document.id
            record.failure_reason = None
            self.jobs.complete(job.id)
            self.session.add(
                DocumentVersion(
                    id=str(uuid4()),
                    document_id=document.id,
                    version=1,
                    source="user_submission",
                    tags=[],
                )
            )
            self.audit.record(
                AuditRecord(
                    actor_user_id=actor_user_id,
                    action="knowledge_submission.published",
                    object_type="knowledge_submission",
                    object_id=record.id,
                    request_id=request_id,
                    details={"document_id": document.id, "job_id": job.id},
                )
            )
            self.session.commit()
            self.session.refresh(record)
        except Exception as exc:
            self.session.rollback()
            cleanup_failed = False
            if document is not None:
                try:
                    current = self.lifecycle.repository.get_by_id(document.id)
                    if current is not None:
                        self.lifecycle.delete_document(current)
                except Exception:
                    cleanup_failed = True
            record = self._get(submission_id)
            record.status = "failed"
            record.failure_reason = (
                "PUBLISH_CLEANUP_UNCERTAIN" if cleanup_failed else type(exc).__name__
            )
            self.jobs.fail(job.id, record.failure_reason)
            self.session.commit()
            raise DocumentStoreError() from exc

        self._cleanup_isolated_after_publication(
            isolated_path,
            record=record,
            job_id=job.id,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        return ApprovalResponse(submission=self._to_item(record), job_id=job.id)

    async def retry_failed(
        self,
        submission_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ApprovalResponse:
        return await self._publish(
            submission_id,
            expected_status="failed",
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def _cleanup_isolated_after_publication(
        self,
        isolated_path,
        *,
        record: KnowledgeSubmission,
        job_id: str,
        actor_user_id: str,
        request_id: str | None,
    ) -> None:
        """发布提交后只做尽力清理；失败不能反向撤销已发布资产。"""

        try:
            isolated_path.unlink(missing_ok=True)
            self.asset_store.cleanup_submission_assets(record.id)
        except OSError as exc:
            try:
                self.audit.record(
                    AuditRecord(
                        actor_user_id=actor_user_id,
                        action="knowledge_submission.cleanup_pending",
                        object_type="knowledge_submission",
                        object_id=record.id,
                        result="warning",
                        request_id=request_id,
                        details={
                            "job_id": job_id,
                            "error_type": type(exc).__name__,
                        },
                    )
                )
                self.session.commit()
            except Exception:
                self.session.rollback()

    def _get(self, submission_id: str) -> KnowledgeSubmission:
        record = self.repository.get_by_id(submission_id)
        if record is None:
            raise ReviewNotFoundError()
        return record

    @staticmethod
    def _to_item(record: KnowledgeSubmission) -> ReviewItem:
        return ReviewItem(
            submission_id=record.id,
            submitter_id=record.submitter_id,
            file_name=record.original_name,
            content_hash=record.content_hash,
            size_bytes=record.size_bytes,
            status=record.status,
            preview_text=record.preview_text,
            preview_pages=record.preview_pages,
            parse_warnings=list(record.parse_warnings or []),
            parse_quality=dict(record.parse_quality or {}),
            rejection_reason=record.rejection_reason,
            failure_reason=record.failure_reason,
            document_id=record.document_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
