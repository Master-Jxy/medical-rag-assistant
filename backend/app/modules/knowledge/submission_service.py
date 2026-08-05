"""普通用户资料隔离提交、无费用解析与撤回用例。"""

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentParseError,
    DocumentStoreError,
    DuplicateDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.modules.knowledge.asset_storage import (
    ControlledDocumentAssetStore,
    StagedAssetDeletion,
)
from app.modules.knowledge.deduplication import DuplicatePolicy
from app.modules.knowledge.enrichment import DocumentEnrichmentService
from app.modules.knowledge.ingestion import FileTypePolicy, ParseRequest
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeSubmission
from app.modules.knowledge.parser import ParsedPreview, ParserPort
from app.modules.knowledge.schemas import SubmissionCreateResponse
from app.modules.knowledge.web_snapshot import WebSnapshotFetchPort
from app.services.upload_protection_service import UploadProtectionService

READ_BLOCK_SIZE = 1024 * 1024
logger = logging.getLogger(__name__)


class SubmissionNotWithdrawableError(DocumentParseError):
    def __init__(self) -> None:
        super().__init__("当前资料状态不能撤回")
        self.code = "SUBMISSION_NOT_WITHDRAWABLE"
        self.status_code = 409


class KnowledgeSubmissionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        parser: ParserPort,
        upload_protection: UploadProtectionService | None = None,
        web_snapshot_fetcher: WebSnapshotFetchPort | None = None,
        asset_store: ControlledDocumentAssetStore | None = None,
        enrichment_service: DocumentEnrichmentService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.parser = parser
        self.upload_protection = upload_protection
        self.web_snapshot_fetcher = web_snapshot_fetcher
        self.asset_store = asset_store or ControlledDocumentAssetStore(settings)
        self.enrichment_service = enrichment_service

    async def submit(self, user_id: str, upload_file: UploadFile) -> SubmissionCreateResponse:
        async def operation() -> KnowledgeSubmission:
            return await self._save_and_parse(user_id, upload_file)

        try:
            record = (
                await self.upload_protection.execute(user_id, operation)
                if self.upload_protection
                else await operation()
            )
        finally:
            await upload_file.close()
        return self._to_response(record)

    async def submit_url(self, user_id: str, url: str) -> SubmissionCreateResponse:
        if self.web_snapshot_fetcher is None:
            raise DocumentParseError("网页快照导入当前不可用")

        async def operation() -> KnowledgeSubmission:
            return await self._fetch_save_and_parse(user_id, url)

        record = (
            await self.upload_protection.execute(user_id, operation)
            if self.upload_protection
            else await operation()
        )
        return self._to_response(record)

    async def _save_and_parse(
        self, user_id: str, upload_file: UploadFile
    ) -> KnowledgeSubmission:
        original_name = Path(upload_file.filename or "").name
        suffix = Path(original_name).suffix.lower()
        FileTypePolicy.get(suffix)
        self.settings.submission_dir.mkdir(parents=True, exist_ok=True)
        submission_id = str(uuid4())
        temporary = self.settings.submission_dir / f".{submission_id}.uploading"
        final_path = self.settings.submission_dir / f"{submission_id}{suffix}"
        record: KnowledgeSubmission | None = None
        try:
            digest = hashlib.sha256()
            size = 0
            with temporary.open("wb") as output:
                while block := await upload_file.read(READ_BLOCK_SIZE):
                    size += len(block)
                    if size > self.settings.max_upload_size_bytes:
                        raise FileTooLargeError(
                            self.settings.max_upload_size_bytes // 1024 // 1024
                        )
                    digest.update(block)
                    output.write(block)
            if size == 0:
                raise DocumentParseError("上传文件为空")
            content_hash = digest.hexdigest()
            duplicate = self.session.scalar(
                select(KnowledgeSubmission.id).where(
                    KnowledgeSubmission.content_hash == content_hash
                )
            ) or self.session.scalar(
                select(KnowledgeDocument.id).where(
                    KnowledgeDocument.content_hash == content_hash
                )
            )
            if duplicate:
                raise DuplicateDocumentError()
            file_type = FileTypePolicy.validate_path(temporary, suffix)
            temporary.replace(final_path)
            record = KnowledgeSubmission(
                id=submission_id,
                submitter_id=user_id,
                original_name=original_name,
                stored_name=final_path.name,
                content_hash=content_hash,
                size_bytes=size,
                status="pending_parse",
                parse_warnings=[],
            )
            self.session.add(record)
            self.session.commit()
            try:
                preview = self._parse_preview(
                    final_path,
                    file_type.suffix,
                    file_name=original_name,
                    submission_id=record.id,
                    user_id=user_id,
                )
                record.preview_text = preview.text
                record.preview_pages = preview.page_count
                record.parse_warnings = list(preview.warnings)
                record.parse_quality = preview.quality or {}
                DuplicatePolicy.assign_to_submission(record)
                record.status = "pending_review"
            except DocumentParseError:
                self.asset_store.cleanup_submission_assets(record.id)
                record.status = "failed"
                record.failure_reason = "DOCUMENT_PARSE_ERROR"
            self.session.commit()
            self.session.refresh(record)
            return record
        except Exception:
            self.session.rollback()
            if record is None:
                final_path.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    async def _fetch_save_and_parse(self, user_id: str, url: str) -> KnowledgeSubmission:
        snapshot = await self.web_snapshot_fetcher.fetch(url)
        duplicate = self.session.scalar(
            select(KnowledgeSubmission.id).where(
                KnowledgeSubmission.content_hash == snapshot.content_sha256
            )
        ) or self.session.scalar(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.content_hash == snapshot.content_sha256
            )
        )
        if duplicate:
            raise DuplicateDocumentError()
        size = len(snapshot.content)
        if size == 0:
            raise DocumentParseError("网页正文为空")
        if size > self.settings.max_upload_size_bytes:
            raise FileTooLargeError(self.settings.max_upload_size_bytes // 1024 // 1024)

        self.settings.submission_dir.mkdir(parents=True, exist_ok=True)
        submission_id = str(uuid4())
        temporary = self.settings.submission_dir / f".{submission_id}.snapshot"
        final_path = self.settings.submission_dir / f"{submission_id}.html"
        record: KnowledgeSubmission | None = None
        try:
            temporary.write_bytes(snapshot.content)
            file_type = FileTypePolicy.validate_path(temporary, ".html")
            temporary.replace(final_path)
            record = KnowledgeSubmission(
                id=submission_id,
                submitter_id=user_id,
                original_name=self._snapshot_file_name(snapshot.final_url),
                stored_name=final_path.name,
                content_hash=snapshot.content_sha256,
                size_bytes=size,
                status="pending_parse",
                parse_warnings=[],
                snapshot_original_url=snapshot.original_url,
                snapshot_final_url=snapshot.final_url,
                snapshot_fetched_at=snapshot.fetched_at,
                snapshot_response_mime=snapshot.mime_type,
                snapshot_content_sha256=snapshot.content_sha256,
            )
            self.session.add(record)
            self.session.commit()
            try:
                preview = self._parse_preview(
                    final_path,
                    file_type.suffix,
                    file_name=record.original_name,
                    submission_id=record.id,
                    user_id=user_id,
                )
                record.preview_text = preview.text
                record.preview_pages = preview.page_count
                record.parse_warnings = list(preview.warnings)
                record.parse_quality = preview.quality or {}
                DuplicatePolicy.assign_to_submission(record)
                record.status = "pending_review"
            except DocumentParseError:
                self.asset_store.cleanup_submission_assets(record.id)
                record.status = "failed"
                record.failure_reason = "DOCUMENT_PARSE_ERROR"
            self.session.commit()
            self.session.refresh(record)
            return record
        except Exception:
            self.session.rollback()
            if record is None:
                final_path.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def withdraw(self, user_id: str, submission_id: str) -> SubmissionCreateResponse:
        record = self.session.scalar(
            select(KnowledgeSubmission).where(
                KnowledgeSubmission.id == submission_id,
                KnowledgeSubmission.submitter_id == user_id,
            )
        )
        if record is None:
            raise DocumentNotFoundError()
        if record.status not in {"pending_parse", "pending_review"}:
            raise SubmissionNotWithdrawableError()
        stored_path = self.settings.submission_dir / record.stored_name
        tombstone_path = self.settings.submission_dir / f".{record.stored_name}.withdrawn"
        file_moved = False
        asset_deletion: StagedAssetDeletion | None = None
        try:
            asset_deletion = self.asset_store.stage_submission_assets_for_delete(record.id)
            if stored_path.exists():
                stored_path.replace(tombstone_path)
                file_moved = True
            record.status = "withdrawn"
            self.session.commit()
        except Exception:
            self.session.rollback()
            if file_moved and tombstone_path.exists():
                tombstone_path.replace(stored_path)
            if asset_deletion is not None:
                self.asset_store.restore_staged_deletion(asset_deletion)
            raise
        try:
            tombstone_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._finalize_submission_assets_after_commit(asset_deletion)
        self.session.refresh(record)
        return self._to_response(record)

    def _finalize_submission_assets_after_commit(
        self,
        staged: StagedAssetDeletion | None,
    ) -> None:
        if staged is None:
            return
        try:
            self.asset_store.finalize_staged_deletion(staged)
        except DocumentStoreError as exc:
            marker_written = self.asset_store.try_mark_cleanup_pending(
                staged,
                reason=type(exc).__name__,
            )
            logger.warning(
                "submission_asset_cleanup_pending",
                extra={
                    "asset_scope": staged.scope,
                    "object_id": staged.object_id,
                    "error_type": type(exc).__name__,
                    "marker_written": marker_written,
                },
            )

    def _parse_preview(
        self,
        path: Path,
        suffix: str,
        *,
        file_name: str,
        submission_id: str,
        user_id: str,
    ) -> ParsedPreview:
        parse_document = getattr(self.parser, "parse_document", None)
        if parse_document is None:
            return self.parser.parse(path, suffix)
        document = parse_document(ParseRequest(path=path, suffix=suffix, file_name=file_name))
        if document.assets:
            document = self.asset_store.materialize_submission_assets(
                document,
                submission_id=submission_id,
                source_path=path,
            )
            if self.enrichment_service is not None:
                document = self.enrichment_service.enrich(document, user_id=user_id)
        return ParsedPreview.from_document(document)

    @staticmethod
    def _to_response(record: KnowledgeSubmission) -> SubmissionCreateResponse:
        return SubmissionCreateResponse(
            submission_id=record.id,
            file_name=record.original_name,
            status=record.status,
            rejection_reason=record.rejection_reason,
            failure_reason=record.failure_reason,
            can_withdraw=record.status in {"pending_parse", "pending_review"},
            submitted_at=record.created_at,
            document_id=record.document_id,
        )

    @staticmethod
    def _snapshot_file_name(final_url: str) -> str:
        host = (urlsplit(final_url).hostname or "web").encode("idna").decode("ascii")
        safe_host = "".join(
            char if char.isalnum() or char in {".", "-"} else "-"
            for char in host.lower()
        ).strip(".-") or "web"
        return f"网页快照-{safe_host[:180]}.html"
