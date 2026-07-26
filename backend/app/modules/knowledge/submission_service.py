"""普通用户资料隔离提交、无费用解析与撤回用例。"""

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentParseError,
    DuplicateDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeSubmission
from app.modules.knowledge.parser import ParserPort
from app.modules.knowledge.schemas import SubmissionCreateResponse
from app.services.upload_protection_service import UploadProtectionService

ALLOWED_SUFFIXES = {".pdf", ".txt"}
READ_BLOCK_SIZE = 1024 * 1024


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
    ) -> None:
        self.session = session
        self.settings = settings
        self.parser = parser
        self.upload_protection = upload_protection

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

    async def _save_and_parse(
        self, user_id: str, upload_file: UploadFile
    ) -> KnowledgeSubmission:
        original_name = Path(upload_file.filename or "").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise UnsupportedFileTypeError()
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
                preview = self.parser.parse(final_path, suffix)
                record.preview_text = preview.text
                record.preview_pages = preview.page_count
                record.parse_warnings = list(preview.warnings)
                record.parse_quality = preview.quality or {}
                record.status = "pending_review"
            except DocumentParseError:
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
        (self.settings.submission_dir / record.stored_name).unlink(missing_ok=True)
        record.status = "withdrawn"
        self.session.commit()
        self.session.refresh(record)
        return self._to_response(record)

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
