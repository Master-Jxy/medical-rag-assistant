"""管理员审核与发布编排；并发状态由原子迁移裁决。"""

import logging
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, DocumentStoreError
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.jobs.ports import JobPort
from app.modules.knowledge.asset_storage import (
    ControlledDocumentAssetStore,
    StagedAssetDeletion,
)
from app.modules.knowledge.deduplication import (
    DuplicateCandidate,
    DuplicateCandidateService,
    DuplicatePolicy,
)
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.models import (
    DocumentVersion,
    KnowledgeDocument,
    KnowledgeSubmission,
)
from app.modules.knowledge.metadata_suggestions import MetadataSuggestionService
from app.modules.knowledge.repository import SubmissionReviewRepository
from app.modules.knowledge.review_schemas import (
    ApprovalResponse,
    ApproveAsVersionRequest,
    DuplicateCandidateItem,
    ReviewItem,
    ReviewListResponse,
)


logger = logging.getLogger(__name__)


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
        metadata_suggestions: MetadataSuggestionService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.lifecycle = lifecycle
        self.audit = audit
        self.jobs = jobs
        self.repository = repository or SubmissionReviewRepository(session)
        self.asset_store = asset_store or ControlledDocumentAssetStore(settings)
        self.metadata_suggestions = metadata_suggestions or MetadataSuggestionService(
            session, audit
        )

    def list_reviews(
        self,
        *,
        status: str | None,
        offset: int,
        limit: int,
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
        suggestions_by_submission = (
            self.metadata_suggestions.get_existing_for_submissions(
                [record.id for record in records]
            )
        )
        items = [
            self._to_item(record, suggestions_by_submission.get(record.id))
            for record in records
        ]
        return ReviewListResponse(
            items=items,
            total=self.session.scalar(count_statement) or 0,
            offset=offset,
            limit=limit,
        )

    def get_review(self, submission_id: str) -> ReviewItem:
        record = self._get(submission_id)
        suggestion = self.metadata_suggestions.get_existing_for_submission(record.id)
        return self._to_item(record, suggestion)

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
        asset_deletion = self.asset_store.stage_submission_assets_for_delete(record.id)
        try:
            if not self.repository.reject_pending(submission_id, normalized_reason):
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
        except Exception:
            self.session.rollback()
            self.asset_store.restore_staged_deletion(asset_deletion)
            raise
        self._finalize_submission_assets_after_commit(
            asset_deletion,
            record=record,
            action="knowledge_submission.cleanup_pending",
            actor_user_id=actor_user_id,
            request_id=request_id,
            details={},
        )
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
            duplicate_decision="new",
            change_reason="管理员批准发布",
        )

    async def approve_as_version(
        self,
        submission_id: str,
        payload: ApproveAsVersionRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ApprovalResponse:
        return await self._publish(
            submission_id,
            expected_status="pending_review",
            actor_user_id=actor_user_id,
            request_id=request_id,
            duplicate_decision="version",
            supersedes_document_id=payload.supersedes_document_id,
            change_reason=payload.change_reason.strip(),
        )

    async def _publish(
        self,
        submission_id: str,
        *,
        expected_status: str,
        actor_user_id: str,
        request_id: str | None,
        duplicate_decision: str,
        supersedes_document_id: str | None = None,
        change_reason: str = "管理员批准发布",
    ) -> ApprovalResponse:
        record = self._get(submission_id)
        superseded: KnowledgeDocument | None = None
        superseded_version: DocumentVersion | None = None
        superseded_snapshot: dict | None = None
        superseded_vectors_deleted = False
        if supersedes_document_id is not None:
            if supersedes_document_id == record.document_id:
                raise ReviewStateConflictError()
            try:
                superseded = self.lifecycle.repository.get_by_id_for_update(
                    supersedes_document_id
                )
            except Exception as exc:
                self.session.rollback()
                raise ReviewStateConflictError() from exc
            if superseded is None or superseded.status not in {"published", "ready"}:
                self.session.rollback()
                raise ReviewStateConflictError()
            superseded_version = self.session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == superseded.id
                )
            )
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
            record.duplicate_decision = duplicate_decision
            record.duplicate_target_document_id = supersedes_document_id
            record.duplicate_decision_reason = change_reason
            record.failure_reason = None
            self.jobs.complete(job.id)
            if record.normalized_text_hash is None:
                DuplicatePolicy.assign_to_submission(record)
            if superseded is not None:
                superseded_snapshot = self.lifecycle.vector_store.snapshot_documents(
                    superseded.chunk_ids
                )
                if set(superseded_snapshot.get("ids") or []) != set(
                    superseded.chunk_ids
                ):
                    raise DocumentStoreError()
                self.lifecycle.vector_store.delete_documents(superseded.chunk_ids)
                superseded_vectors_deleted = True
                superseded.status = "archived"
            version = DocumentVersion(
                id=str(uuid4()),
                document_id=document.id,
                version=(
                    (superseded_version.version if superseded_version else 1) + 1
                    if superseded is not None
                    else 1
                ),
                replaces_document_id=superseded.id if superseded else None,
                supersedes_document_id=superseded.id if superseded else None,
                change_reason=change_reason,
                parser_version="knowledge_parser_v1",
                corpus_version=self.settings.knowledge_base_version,
                source="user_submission",
                tags=[],
            )
            DuplicatePolicy.apply_to_version_from_submission(
                record,
                version,
                parser_version="knowledge_parser_v1",
                corpus_version=self.settings.knowledge_base_version,
                change_reason=change_reason,
            )
            self.metadata_suggestions.apply_confirmed_to_version(record, version)
            self.session.add(version)
            self.audit.record(
                AuditRecord(
                    actor_user_id=actor_user_id,
                    action="knowledge_submission.published",
                    object_type="knowledge_submission",
                    object_id=record.id,
                    request_id=request_id,
                    details={
                        "document_id": document.id,
                        "job_id": job.id,
                        "duplicate_decision": duplicate_decision,
                        "supersedes_document_id": supersedes_document_id,
                    },
                )
            )
            self.session.commit()
            self.session.refresh(record)
        except Exception as exc:
            self.session.rollback()
            cleanup_failed = False
            if superseded_vectors_deleted and superseded_snapshot is not None:
                try:
                    self.lifecycle.vector_store.restore_documents(superseded_snapshot)
                except Exception:
                    cleanup_failed = True
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
            duplicate_decision="new",
            change_reason="管理员重试发布",
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
            staged_assets = self.asset_store.stage_submission_assets_for_delete(record.id)
            isolated_path.unlink(missing_ok=True)
            self.asset_store.finalize_staged_deletion(staged_assets)
        except (OSError, DocumentStoreError) as exc:
            if "staged_assets" in locals():
                marker_written = self.asset_store.try_mark_cleanup_pending(
                    staged_assets,
                    reason=type(exc).__name__,
                )
                if not marker_written:
                    logger.warning(
                        "review_submission_asset_cleanup_marker_failed",
                        extra={
                            "asset_scope": staged_assets.scope,
                            "object_id": staged_assets.object_id,
                            "error_type": type(exc).__name__,
                        },
                    )
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

    def _finalize_submission_assets_after_commit(
        self,
        staged: StagedAssetDeletion,
        *,
        record: KnowledgeSubmission,
        action: str,
        actor_user_id: str,
        request_id: str | None,
        details: dict,
    ) -> None:
        try:
            self.asset_store.finalize_staged_deletion(staged)
        except DocumentStoreError as exc:
            marker_written = self.asset_store.try_mark_cleanup_pending(
                staged,
                reason=type(exc).__name__,
            )
            if not marker_written:
                logger.warning(
                    "review_submission_asset_cleanup_marker_failed",
                    extra={
                        "asset_scope": staged.scope,
                        "object_id": staged.object_id,
                        "error_type": type(exc).__name__,
                    },
                )
            try:
                self.audit.record(
                    AuditRecord(
                        actor_user_id=actor_user_id,
                        action=action,
                        object_type="knowledge_submission",
                        object_id=record.id,
                        result="warning",
                        request_id=request_id,
                        details={"error_type": type(exc).__name__, **details},
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

    def _to_item(self, record: KnowledgeSubmission, suggestion=None) -> ReviewItem:
        duplicate_candidates = DuplicateCandidateService(self.session).for_submission(
            record
        )
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
            metadata_suggestion=(
                self.metadata_suggestions.to_item(suggestion) if suggestion else None
            ),
            duplicate_candidates=[
                self._duplicate_candidate_to_item(candidate)
                for candidate in duplicate_candidates
            ],
            duplicate_decision=record.duplicate_decision,
            duplicate_target_document_id=record.duplicate_target_document_id,
            normalized_text_hash_version=record.normalized_text_hash_version,
            near_duplicate_fingerprint_version=record.near_duplicate_fingerprint_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _duplicate_candidate_to_item(
        candidate: DuplicateCandidate,
    ) -> DuplicateCandidateItem:
        return DuplicateCandidateItem(
            duplicate_type=candidate.duplicate_type,
            candidate_document_id=candidate.candidate_document_id,
            candidate_file_name=candidate.candidate_file_name,
            candidate_version=candidate.candidate_version,
            score=candidate.score,
            distance=candidate.distance,
            threshold=candidate.threshold,
            reason=candidate.reason,
        )
