"""知识资产查询、元数据、下线、重发和替换编排。"""

from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, DocumentBusyError, DocumentStoreError
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.knowledge.asset_schemas import (
    KnowledgeAssetItem,
    KnowledgeAssetListResponse,
)
from app.modules.knowledge.deduplication import (
    DuplicateCandidate,
    DuplicateCandidateService,
    DuplicatePolicy,
)
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.models import DocumentVersion, KnowledgeDocument
from app.modules.knowledge.repository import DocumentLockConflictError
from app.modules.knowledge.review_schemas import DuplicateCandidateItem
from app.modules.jobs.ports import JobPort


class AssetNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("未找到知识资产", code="ASSET_NOT_FOUND", status_code=404)


class AssetStateConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "当前知识资产状态不允许该操作",
            code="ASSET_STATE_CONFLICT",
            status_code=409,
        )


class KnowledgeAssetService:
    def __init__(
        self,
        session: Session,
        lifecycle: DocumentLifecycleService,
        audit: AuditPort,
        jobs: JobPort | None = None,
    ) -> None:
        self.session = session
        self.lifecycle = lifecycle
        self.audit = audit
        self.jobs = jobs

    def list_assets(
        self,
        *,
        status: str | None,
        source: str | None,
        tag: str | None,
        offset: int,
        limit: int,
        review_status: str | None = None,
        expired: bool | None = None,
    ) -> KnowledgeAssetListResponse:
        statement = select(KnowledgeDocument, DocumentVersion).outerjoin(
            DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id
        )
        count_statement = select(func.count()).select_from(KnowledgeDocument).outerjoin(
            DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id
        )
        conditions = []
        if status:
            conditions.append(KnowledgeDocument.status == status)
        if source:
            conditions.append(DocumentVersion.source == source)
        computed_review_filter = review_status in {"current", "due", "expired"}
        if review_status and not computed_review_filter:
            conditions.append(DocumentVersion.review_status == review_status)
        if expired:
            conditions.extend(
                [
                    DocumentVersion.expires_at.is_not(None),
                    DocumentVersion.expires_at <= datetime.now(timezone.utc),
                ]
            )
        if tag:
            # JSON跨SQLite/MySQL的精确过滤差异较大，先在受控结果内过滤标签。
            pass
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        rows = self.session.execute(
            statement.order_by(
                KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc()
            )
        ).all()
        if tag:
            rows = [row for row in rows if row[1] and tag in (row[1].tags or [])]
        if computed_review_filter and review_status:
            rows = [
                row
                for row in rows
                if DuplicatePolicy.governance_status(row[1]) == review_status
            ]
        total = len(rows) if tag else (self.session.scalar(count_statement) or 0)
        if computed_review_filter:
            total = len(rows)
        page = rows[offset : offset + limit] if tag else rows[offset : offset + limit]
        return KnowledgeAssetListResponse(
            items=[self._to_item(document, version) for document, version in page],
            total=total,
            offset=offset,
            limit=limit,
        )

    def scan_duplicate_fingerprints(self) -> dict:
        if self.jobs is None:
            return {"job_id": None, "scanned": 0, "updated": 0, "failed": 0}
        rows = self.session.execute(
            select(KnowledgeDocument, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.status.in_(("published", "ready", "archived")),
                DocumentVersion.normalized_text_hash.is_(None),
            )
            .order_by(KnowledgeDocument.created_at.asc(), KnowledgeDocument.id.asc())
        ).all()
        if not rows:
            return {"job_id": None, "scanned": 0, "updated": 0, "failed": 0}
        job = self.jobs.start(
            job_type="knowledge_duplicate_scan",
            object_type="knowledge_corpus",
            object_id="public",
            initial_progress=0,
        )
        updated = 0
        failed = 0
        try:
            for document, version in rows:
                try:
                    fingerprint = self.lifecycle.fingerprint_existing_document(document)
                except Exception:
                    failed += 1
                    continue
                version.normalized_text_hash = fingerprint.normalized_text_hash
                version.normalized_text_hash_version = (
                    fingerprint.normalized_text_hash_version
                )
                version.near_duplicate_fingerprint = (
                    fingerprint.near_duplicate_fingerprint
                )
                version.near_duplicate_fingerprint_version = (
                    fingerprint.near_duplicate_fingerprint_version
                )
                version.parser_version = version.parser_version or "knowledge_parser_v1"
                version.corpus_version = version.corpus_version or "live_v1"
                updated += 1
            if failed:
                self.jobs.fail(job.id, "DUPLICATE_SCAN_PARTIAL_FAILURE")
            else:
                self.jobs.complete(job.id)
            self.session.commit()
            return {
                "job_id": job.id,
                "scanned": len(rows),
                "updated": updated,
                "failed": failed,
            }
        except Exception:
            self.session.rollback()
            raise

    def update_metadata(
        self,
        document_id: str,
        *,
        source: str | None,
        tags: list[str],
        actor_user_id: str,
        request_id: str | None,
        category: str | None = None,
        department: str | None = None,
        expires_at: datetime | None = None,
        review_due_at: datetime | None = None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        version = self._get_or_create_version(document)
        version.source = source.strip() if source and source.strip() else None
        version.tags = tags
        version.category = category.strip() if category and category.strip() else None
        version.department = department.strip() if department and department.strip() else None
        version.expires_at = expires_at
        version.review_due_at = review_due_at
        version.review_status = DuplicatePolicy.governance_status(version)
        self._audit(
            "knowledge_asset.metadata_updated",
            document_id,
            actor_user_id,
            request_id,
            {"source": version.source, "tag_count": len(tags), "category": version.category, "department": version.department},
        )
        self.session.commit()
        return self._to_item(document, version)

    def mark_reviewed(
        self,
        document_id: str,
        *,
        next_review_due_at: datetime,
        note: str,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        version = self._get_or_create_version(document)
        now = datetime.now(next_review_due_at.tzinfo or timezone.utc)
        if next_review_due_at <= now:
            raise AssetStateConflictError()
        version.last_reviewed_at = now
        version.review_due_at = next_review_due_at
        version.review_status = "current"
        if self.jobs is not None:
            self.jobs.complete_running_for_object(
                job_type="knowledge_review",
                object_type="knowledge_document",
                object_id=document_id,
            )
        self._audit("knowledge_asset.reviewed", document_id, actor_user_id, request_id, {"note": note, "next_review_due_at": next_review_due_at.isoformat()})
        self.session.commit()
        return self._to_item(document, version)

    def defer_review(
        self,
        document_id: str,
        *,
        next_review_due_at: datetime,
        note: str,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        version = self._get_or_create_version(document)
        now = datetime.now(next_review_due_at.tzinfo or timezone.utc)
        if next_review_due_at <= now:
            raise AssetStateConflictError()
        version.review_due_at = next_review_due_at
        version.review_status = "current"
        self._audit(
            "knowledge_asset.review_deferred",
            document_id,
            actor_user_id,
            request_id,
            {"note": note, "next_review_due_at": next_review_due_at.isoformat()},
        )
        self.session.commit()
        return self._to_item(document, version)

    def mark_expired(
        self,
        document_id: str,
        *,
        reason: str,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        version = self._get_or_create_version(document)
        version.review_status = "expired"
        if version.expires_at is None:
            version.expires_at = datetime.now(timezone.utc)
        self._audit(
            "knowledge_asset.expired_marked",
            document_id,
            actor_user_id,
            request_id,
            {"reason": reason},
        )
        self.session.commit()
        return self._to_item(document, version)

    def restore_current(
        self,
        document_id: str,
        *,
        next_review_due_at: datetime | None,
        note: str,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        version = self._get_or_create_version(document)
        now = datetime.now(timezone.utc)
        version.expires_at = None
        version.last_reviewed_at = now
        version.review_due_at = next_review_due_at
        version.review_status = "current"
        self._audit(
            "knowledge_asset.restored_current",
            document_id,
            actor_user_id,
            request_id,
            {
                "note": note,
                "next_review_due_at": (
                    next_review_due_at.isoformat() if next_review_due_at else None
                ),
            },
        )
        self.session.commit()
        return self._to_item(document, version)

    def archive(
        self,
        document_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        if document.status not in {"published", "ready"}:
            raise AssetStateConflictError()
        version = self._get_or_create_version(document)
        snapshot = self.lifecycle.vector_store.snapshot_documents(document.chunk_ids)
        if set(snapshot.get("ids") or []) != set(document.chunk_ids):
            raise DocumentStoreError()
        try:
            self.lifecycle.vector_store.delete_documents(document.chunk_ids)
            document.status = "archived"
            self._audit(
                "knowledge_asset.archived",
                document.id,
                actor_user_id,
                request_id,
            )
            self.session.commit()
            return self._to_item(document, version)
        except Exception as exc:
            self.session.rollback()
            try:
                self.lifecycle.vector_store.restore_documents(snapshot)
            except Exception:
                pass
            if isinstance(exc, AppError):
                raise
            raise DocumentStoreError() from exc

    def republish(
        self,
        document_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        document = self._get_document(document_id)
        if document.status not in {"archived", "failed"}:
            raise AssetStateConflictError()
        version = self._get_or_create_version(document)
        new_ids: list[str] = []
        try:
            new_ids = self.lifecycle.index_existing_document(document)
            document.chunk_ids = new_ids
            document.chunk_count = len(new_ids)
            document.status = "published"
            self._audit(
                "knowledge_asset.republished",
                document.id,
                actor_user_id,
                request_id,
            )
            self.session.commit()
            return self._to_item(document, version)
        except Exception as exc:
            self.session.rollback()
            if new_ids:
                try:
                    self.lifecycle.vector_store.delete_documents(new_ids)
                except Exception:
                    pass
            if isinstance(exc, AppError):
                raise
            raise DocumentStoreError() from exc

    def replace(
        self,
        old_document_id: str,
        new_document_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> KnowledgeAssetItem:
        if old_document_id == new_document_id:
            raise AssetStateConflictError()
        try:
            old = self.lifecycle.repository.get_by_id_for_update(old_document_id)
        except DocumentLockConflictError as exc:
            self.session.rollback()
            raise DocumentBusyError() from exc
        if old is None:
            raise AssetNotFoundError()
        new = self._get_document(new_document_id)
        if old.status not in {"published", "ready"} or new.status != "published":
            raise AssetStateConflictError()
        old_version = self._get_or_create_version(old)
        new_version = self._get_or_create_version(new)
        snapshot = self.lifecycle.vector_store.snapshot_documents(old.chunk_ids)
        if set(snapshot.get("ids") or []) != set(old.chunk_ids):
            raise DocumentStoreError()
        try:
            self.lifecycle.vector_store.delete_documents(old.chunk_ids)
            old.status = "archived"
            new_version.replaces_document_id = old.id
            new_version.supersedes_document_id = old.id
            new_version.version = old_version.version + 1
            new_version.change_reason = "管理员关联替换"
            new_version.parser_version = (
                new_version.parser_version or "knowledge_parser_v1"
            )
            new_version.corpus_version = (
                new_version.corpus_version
                or self.lifecycle.settings.knowledge_base_version
            )
            self._audit(
                "knowledge_asset.replaced",
                old.id,
                actor_user_id,
                request_id,
                {"replacement_document_id": new.id},
            )
            self.session.commit()
            return self._to_item(new, new_version)
        except Exception as exc:
            self.session.rollback()
            try:
                self.lifecycle.vector_store.restore_documents(snapshot)
            except Exception:
                pass
            raise DocumentStoreError() from exc

    def _get_document(self, document_id: str) -> KnowledgeDocument:
        document = self.session.get(KnowledgeDocument, document_id)
        if document is None:
            raise AssetNotFoundError()
        return document

    def _get_or_create_version(self, document: KnowledgeDocument) -> DocumentVersion:
        version = self.session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id)
        )
        if version is None:
            version = DocumentVersion(
                id=str(uuid4()),
                document_id=document.id,
                version=1,
                source="system" if document.is_system else "legacy_upload",
                tags=[],
                parser_version="knowledge_parser_v1",
                corpus_version=self.lifecycle.settings.knowledge_base_version,
            )
            self.session.add(version)
            self.session.flush()
        return version

    def _audit(
        self,
        action: str,
        object_id: str,
        actor_user_id: str,
        request_id: str | None,
        details: dict | None = None,
    ) -> None:
        self.audit.record(
            AuditRecord(
                actor_user_id=actor_user_id,
                action=action,
                object_type="knowledge_document",
                object_id=object_id,
                request_id=request_id,
                details=details or {},
            )
        )

    def _to_item(
        self, document: KnowledgeDocument, version: DocumentVersion | None
    ) -> KnowledgeAssetItem:
        duplicate_candidates = DuplicateCandidateService(self.session).for_document(
            document, version
        )
        governance_status = DuplicatePolicy.governance_status(version)
        return KnowledgeAssetItem(
            document_id=document.id,
            file_name=document.original_name,
            is_system=document.is_system,
            status="published" if document.status == "ready" else document.status,
            source=version.source if version else None,
            tags=list(version.tags or []) if version else [],
            version=version.version if version else 1,
            replaces_document_id=version.replaces_document_id if version else None,
            chunk_count=document.chunk_count,
            updated_at=document.created_at,
            category=version.category if version else None,
            department=version.department if version else None,
            disease_topics=list(version.disease_topics or []) if version else [],
            document_type=version.document_type if version else None,
            published_year=version.published_year if version else None,
            expires_at=version.expires_at if version else None,
            review_due_at=version.review_due_at if version else None,
            last_reviewed_at=version.last_reviewed_at if version else None,
            review_status=(version.review_status or "current") if version else "current",
            governance_status=governance_status,
            is_expired=governance_status == "expired",
            supersedes_document_id=version.supersedes_document_id if version else None,
            change_reason=version.change_reason if version else None,
            parser_version=version.parser_version if version else None,
            corpus_version=version.corpus_version if version else None,
            normalized_text_hash_version=(
                version.normalized_text_hash_version if version else None
            ),
            near_duplicate_fingerprint_version=(
                version.near_duplicate_fingerprint_version if version else None
            ),
            duplicate_candidates=[
                self._duplicate_candidate_to_item(candidate)
                for candidate in duplicate_candidates
            ],
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
