"""文档在 MySQL、文件系统与 Chroma 之间的共享生命周期。"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    DocumentBusyError,
    DocumentNotFoundError,
    DocumentParseError,
    DocumentStoreError,
    DuplicateDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.infrastructure.vector_store import VectorStoreService
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.knowledge.asset_storage import (
    ControlledDocumentAssetStore,
    StagedAssetDeletion,
)
from app.modules.knowledge.ingestion import (
    FileTypePolicy,
    ParseRequest,
    ParsedDocument,
    ParsedElement,
)
from app.modules.knowledge.models import (
    DocumentVersion,
    KnowledgeDocument,
    KnowledgeSubmission,
)
from app.modules.knowledge.repository import (
    DocumentLockConflictError,
    DocumentRepository,
)
from app.modules.knowledge.parser import LocalDocumentParser

READ_BLOCK_SIZE = 1024 * 1024


@dataclass
class PreparedDocument:
    record: KnowledgeDocument
    final_path: Path
    chunk_ids: list[str]
    vectors_added: bool = True


class DocumentLifecycleService:
    """集中实现跨 MySQL、文件系统和向量库的文档生命周期。"""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        vector_store: VectorStoreService,
        repository: DocumentRepository | None = None,
        parser: LocalDocumentParser | None = None,
        asset_store: ControlledDocumentAssetStore | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.vector_store = vector_store
        self.repository = repository or DocumentRepository(session)
        self.parser = parser or LocalDocumentParser()
        self.asset_store = asset_store or ControlledDocumentAssetStore(settings)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )

    async def create_document(
        self,
        upload_file: UploadFile,
        *,
        uploader_id: str | None,
        is_system: bool,
    ) -> KnowledgeDocument:
        prepared: PreparedDocument | None = None
        try:
            prepared = await self._prepare_upload(
                upload_file, uploader_id=uploader_id, is_system=is_system
            )
            self.repository.add(prepared.record)
            self.session.commit()
            self.session.refresh(prepared.record)
            return prepared.record
        except IntegrityError as exc:
            self.session.rollback()
            if prepared is not None:
                self._cleanup_prepared(prepared)
            raise DuplicateDocumentError() from exc
        except (
            UnsupportedFileTypeError,
            FileTooLargeError,
            DuplicateDocumentError,
            DocumentParseError,
        ):
            self.session.rollback()
            if prepared is not None:
                self._cleanup_prepared(prepared)
            raise
        except Exception as exc:
            self.session.rollback()
            if prepared is not None:
                self._cleanup_prepared(prepared)
            raise DocumentStoreError() from exc
        finally:
            await upload_file.close()

    def delete_document(self, record: KnowledgeDocument) -> str:
        stored_path = self.settings.upload_dir / record.stored_name
        tombstone_path = self.settings.upload_dir / f".{record.stored_name}.deleting"
        snapshot: dict | None = None
        file_moved = False
        delete_started = False
        asset_deletion: StagedAssetDeletion | None = None

        try:
            snapshot = self.vector_store.snapshot_documents(record.chunk_ids)
            if set(snapshot.get("ids") or []) != set(record.chunk_ids):
                raise DocumentStoreError()
            if not stored_path.is_file():
                raise DocumentStoreError()

            asset_deletion = self.asset_store.stage_document_assets_for_delete(record.id)
            stored_path.replace(tombstone_path)
            file_moved = True
            delete_started = True
            self.vector_store.delete_documents(record.chunk_ids)
            self.repository.delete(record)
            self.session.commit()
        except DocumentStoreError:
            self.session.rollback()
            self._restore_delete(
                stored_path, tombstone_path, snapshot, file_moved, delete_started
            )
            self._restore_staged_assets(asset_deletion)
            raise
        except Exception as exc:
            self.session.rollback()
            try:
                self._restore_delete(
                    stored_path, tombstone_path, snapshot, file_moved, delete_started
                )
                self._restore_staged_assets(asset_deletion)
            except Exception:
                pass
            raise DocumentStoreError() from exc
        try:
            tombstone_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._finalize_staged_assets_after_commit(asset_deletion)
        return record.id

    async def replace_document(
        self,
        document_id: str,
        upload_file: UploadFile,
        *,
        audit: AuditPort | None = None,
        actor_user_id: str | None = None,
        request_id: str | None = None,
        reason: str = "管理员整份替换",
    ) -> KnowledgeDocument:
        prepared: PreparedDocument | None = None
        old_snapshot: dict | None = None
        old_record: KnowledgeDocument | None = None
        old_copy: KnowledgeDocument | None = None
        old_version_values: dict | None = None
        submission_states: list[dict] = []
        switched = False
        old_file_moved = False
        old_delete_started = False
        tombstone_path: Path | None = None
        asset_deletion: StagedAssetDeletion | None = None

        try:
            try:
                old_record = self.repository.get_by_id_for_update(document_id)
            except DocumentLockConflictError as exc:
                self.session.rollback()
                raise DocumentBusyError() from exc
            if old_record is None:
                raise DocumentNotFoundError()

            old_copy = self._copy_record(old_record)
            old_version = self.session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == old_record.id
                )
            )
            old_version_values = self._copy_version_values(old_version)
            linked_submissions = self.session.scalars(
                select(KnowledgeSubmission).where(
                    KnowledgeSubmission.document_id == old_record.id
                )
            ).all()
            submission_states = [
                self._copy_submission_state(submission)
                for submission in linked_submissions
            ]
            old_path = self.settings.upload_dir / old_record.stored_name
            tombstone_path = self.settings.upload_dir / f".{old_record.stored_name}.replacing"
            if not old_path.is_file():
                raise DocumentStoreError()
            old_snapshot = self.vector_store.snapshot_documents(old_record.chunk_ids)
            if old_record.status in {"published", "ready"} and set(
                old_snapshot.get("ids") or []
            ) != set(old_record.chunk_ids):
                raise DocumentStoreError()

            asset_deletion = self.asset_store.stage_document_assets_for_delete(old_record.id)
            prepared = await self._prepare_upload(
                upload_file,
                uploader_id=old_record.uploader_id,
                is_system=old_record.is_system,
            )
            for submission in linked_submissions:
                submission.document_id = None
            self.session.flush()
            if old_version is not None:
                self.session.delete(old_version)
            self.repository.delete(old_record)
            self.session.flush()
            self.repository.add(prepared.record)
            self.session.flush()
            self.session.add(
                self._build_replacement_version(
                    prepared.record,
                    old_version_values,
                )
            )
            for submission in linked_submissions:
                self._sync_published_submission(submission, prepared.record)
            self.session.commit()
            switched = True

            old_path.replace(tombstone_path)
            old_file_moved = True
            old_delete_started = True
            self.vector_store.delete_documents(old_copy.chunk_ids)
            if audit is not None and actor_user_id is not None:
                audit.record(
                    AuditRecord(
                        actor_user_id=actor_user_id,
                        action="knowledge_asset.file_replaced",
                        object_type="knowledge_document",
                        object_id=old_copy.id,
                        request_id=request_id,
                        details={
                            "replacement_document_id": prepared.record.id,
                            "source_type": self._source_type(
                                old_copy, old_version_values
                            ),
                            "reason": reason,
                        },
                    )
                )
                self.session.commit()
            try:
                tombstone_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.session.refresh(prepared.record)
        except (
            DocumentNotFoundError,
            DocumentBusyError,
            UnsupportedFileTypeError,
            FileTooLargeError,
            DuplicateDocumentError,
            DocumentParseError,
        ):
            self.session.rollback()
            if prepared is not None and not switched:
                self._cleanup_prepared(prepared)
            self._restore_staged_assets(asset_deletion)
            raise
        except IntegrityError as exc:
            self.session.rollback()
            if prepared is not None and not switched:
                self._cleanup_prepared(prepared)
            self._restore_staged_assets(asset_deletion)
            raise DuplicateDocumentError() from exc
        except Exception as exc:
            self.session.rollback()
            if switched and prepared is not None and old_copy is not None:
                try:
                    self._restore_delete(
                        self.settings.upload_dir / old_copy.stored_name,
                        tombstone_path
                        or self.settings.upload_dir
                        / f".{old_copy.stored_name}.replacing",
                        old_snapshot,
                        old_file_moved,
                        old_delete_started,
                    )
                    self._restore_replaced_database(
                        prepared,
                        old_copy,
                        old_version_values,
                        submission_states,
                    )
                    self._restore_staged_assets(asset_deletion)
                except Exception:
                    pass
            elif prepared is not None:
                self._cleanup_prepared(prepared)
                self._restore_staged_assets(asset_deletion)
            raise DocumentStoreError() from exc
        finally:
            await upload_file.close()
        self._finalize_staged_assets_after_commit(asset_deletion)
        return prepared.record

    async def replace_system_document(
        self, document_id: str, upload_file: UploadFile
    ) -> KnowledgeDocument:
        """兼容旧调用；管理员入口统一改用 replace_document。"""
        return await self.replace_document(document_id, upload_file)

    def delete_managed_document(
        self,
        document_id: str,
        *,
        audit: AuditPort | None = None,
        actor_user_id: str | None = None,
        request_id: str | None = None,
        reason: str = "管理员永久删除",
    ) -> str:
        old_copy: KnowledgeDocument | None = None
        old_version_values: dict | None = None
        submission_states: list[dict] = []
        snapshot: dict | None = None
        file_moved = False
        delete_started = False
        database_deleted = False
        tombstone_path: Path | None = None
        asset_deletion: StagedAssetDeletion | None = None

        try:
            try:
                record = self.repository.get_by_id_for_update(document_id)
            except DocumentLockConflictError as exc:
                self.session.rollback()
                raise DocumentBusyError() from exc
            if record is None:
                raise DocumentNotFoundError()

            old_copy = self._copy_record(record)
            version = self.session.scalar(
                select(DocumentVersion).where(DocumentVersion.document_id == record.id)
            )
            old_version_values = self._copy_version_values(version)
            submissions = self.session.scalars(
                select(KnowledgeSubmission).where(
                    KnowledgeSubmission.document_id == record.id
                )
            ).all()
            submission_states = [
                self._copy_submission_state(submission) for submission in submissions
            ]
            stored_path = self.settings.upload_dir / record.stored_name
            tombstone_path = self.settings.upload_dir / f".{record.stored_name}.deleting"
            if not stored_path.is_file():
                raise DocumentStoreError()
            snapshot = self.vector_store.snapshot_documents(record.chunk_ids)
            if record.status in {"published", "ready"} and set(
                snapshot.get("ids") or []
            ) != set(record.chunk_ids):
                raise DocumentStoreError()

            asset_deletion = self.asset_store.stage_document_assets_for_delete(record.id)
            for submission in submissions:
                submission.status = "archived"
                submission.document_id = None
            self.session.flush()
            if version is not None:
                self.session.delete(version)
            self.repository.delete(record)
            self.session.commit()
            database_deleted = True

            stored_path.replace(tombstone_path)
            file_moved = True
            delete_started = True
            self.vector_store.delete_documents(old_copy.chunk_ids)
            if audit is not None and actor_user_id is not None:
                audit.record(
                    AuditRecord(
                        actor_user_id=actor_user_id,
                        action="knowledge_asset.permanently_deleted",
                        object_type="knowledge_document",
                        object_id=old_copy.id,
                        request_id=request_id,
                        details={
                            "source_type": self._source_type(
                                old_copy, old_version_values
                            ),
                            "reason": reason,
                        },
                    )
                )
                self.session.commit()
            try:
                tombstone_path.unlink(missing_ok=True)
            except OSError:
                pass
        except (DocumentNotFoundError, DocumentBusyError, DocumentStoreError):
            self.session.rollback()
            if database_deleted and old_copy is not None:
                self._restore_delete(
                    self.settings.upload_dir / old_copy.stored_name,
                    tombstone_path
                    or self.settings.upload_dir / f".{old_copy.stored_name}.deleting",
                    snapshot,
                    file_moved,
                    delete_started,
                )
                self._restore_deleted_database(
                    old_copy, old_version_values, submission_states
                )
            self._restore_staged_assets(asset_deletion)
            raise
        except Exception as exc:
            self.session.rollback()
            if database_deleted and old_copy is not None:
                try:
                    self._restore_delete(
                        self.settings.upload_dir / old_copy.stored_name,
                        tombstone_path
                        or self.settings.upload_dir
                        / f".{old_copy.stored_name}.deleting",
                        snapshot,
                        file_moved,
                        delete_started,
                    )
                    self._restore_deleted_database(
                        old_copy, old_version_values, submission_states
                    )
                    self._restore_staged_assets(asset_deletion)
                except Exception:
                    pass
            else:
                self._restore_staged_assets(asset_deletion)
            raise DocumentStoreError() from exc
        self._finalize_staged_assets_after_commit(asset_deletion)
        return old_copy.id

    async def _prepare_upload(
        self,
        upload_file: UploadFile,
        *,
        uploader_id: str | None,
        is_system: bool,
    ) -> PreparedDocument:
        original_name = Path(upload_file.filename or "").name
        suffix = Path(original_name).suffix.lower()
        FileTypePolicy.get(suffix)

        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        document_id = str(uuid4())
        temporary_path = self.settings.upload_dir / f".{document_id}.uploading"
        final_path = self.settings.upload_dir / f"{document_id}{suffix}"
        chunk_ids: list[str] = []
        vectors_added = False
        try:
            file_hash, file_size = await self._save_and_hash(upload_file, temporary_path)
            file_type = FileTypePolicy.validate_path(temporary_path, suffix)
            if self.repository.get_by_hash(file_hash) is not None:
                raise DuplicateDocumentError()
            documents = self._load_documents(temporary_path, file_type.suffix)
            chunks = self._split_documents(
                documents, document_id, original_name, file_hash
            )
            chunk_ids = [f"{document_id}:{index}" for index in range(len(chunks))]
            for chunk, chunk_id in zip(chunks, chunk_ids, strict=True):
                chunk.metadata["chunk_id"] = chunk_id
            self.vector_store.add_documents(chunks, chunk_ids)
            vectors_added = True
            temporary_path.replace(final_path)
            record = KnowledgeDocument(
                id=document_id,
                original_name=original_name,
                stored_name=final_path.name,
                content_hash=file_hash,
                size_bytes=file_size,
                chunk_count=len(chunks),
                chunk_ids=chunk_ids,
                uploader_id=uploader_id,
                is_system=is_system,
                status="published",
                created_at=datetime.now(timezone.utc),
            )
            return PreparedDocument(record, final_path, chunk_ids, vectors_added)
        except Exception:
            if vectors_added:
                try:
                    self.vector_store.delete_documents(chunk_ids)
                except Exception:
                    pass
            final_path.unlink(missing_ok=True)
            raise
        finally:
            temporary_path.unlink(missing_ok=True)

    def _cleanup_prepared(self, prepared: PreparedDocument) -> None:
        if prepared.vectors_added:
            try:
                self.vector_store.delete_documents(prepared.chunk_ids)
            except Exception:
                pass
        prepared.final_path.unlink(missing_ok=True)
        self.asset_store.cleanup_document_assets(prepared.record.id)

    def index_existing_document(self, record: KnowledgeDocument) -> list[str]:
        """从保留原文件重建向量；调用方负责提交文档状态。"""
        path = self.settings.upload_dir / record.stored_name
        suffix = path.suffix.lower()
        if not path.is_file():
            raise DocumentStoreError()
        file_type = FileTypePolicy.validate_path(path, suffix)
        documents = self._load_documents(path, file_type.suffix)
        chunks = self._split_documents(
            documents,
            record.id,
            record.original_name,
            record.content_hash,
        )
        chunk_ids = [f"{record.id}:{index}" for index in range(len(chunks))]
        for chunk, chunk_id in zip(chunks, chunk_ids, strict=True):
            chunk.metadata["chunk_id"] = chunk_id
        try:
            self.vector_store.add_documents(chunks, chunk_ids)
        except Exception as exc:
            try:
                self.vector_store.delete_documents(chunk_ids)
            except Exception:
                pass
            raise DocumentStoreError() from exc
        return chunk_ids

    def _restore_delete(
        self,
        stored_path: Path,
        tombstone_path: Path,
        snapshot: dict | None,
        file_moved: bool,
        delete_started: bool,
    ) -> None:
        if delete_started and snapshot is not None:
            self.vector_store.restore_documents(snapshot)
        if file_moved and tombstone_path.exists():
            tombstone_path.replace(stored_path)

    def _restore_staged_assets(self, staged: StagedAssetDeletion | None) -> None:
        if staged is None:
            return
        self.asset_store.restore_staged_deletion(staged)

    def _finalize_staged_assets_after_commit(
        self,
        staged: StagedAssetDeletion | None,
    ) -> None:
        if staged is None:
            return
        try:
            self.asset_store.finalize_staged_deletion(staged)
        except DocumentStoreError as exc:
            self.asset_store.mark_cleanup_pending(staged, reason=type(exc).__name__)

    def _restore_replaced_database(
        self,
        prepared: PreparedDocument,
        old_record: KnowledgeDocument,
        old_version_values: dict | None,
        submission_states: list[dict],
    ) -> None:
        for state in submission_states:
            submission = self.session.get(KnowledgeSubmission, state["id"])
            if submission is not None:
                submission.document_id = None
        self.session.flush()
        current_version = self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == prepared.record.id
            )
        )
        if current_version is not None:
            self.session.delete(current_version)
        current = self.repository.get_by_id(prepared.record.id)
        if current is not None:
            self.repository.delete(current)
        self.session.flush()
        self.repository.add(old_record)
        self.session.flush()
        if old_version_values is not None:
            self.session.add(
                DocumentVersion(document_id=old_record.id, **old_version_values)
            )
        self._restore_submissions(submission_states)
        self.session.commit()
        self._cleanup_prepared(prepared)

    def _restore_deleted_database(
        self,
        old_record: KnowledgeDocument,
        old_version_values: dict | None,
        submission_states: list[dict],
    ) -> None:
        self.repository.add(old_record)
        self.session.flush()
        if old_version_values is not None:
            self.session.add(
                DocumentVersion(document_id=old_record.id, **old_version_values)
            )
        self._restore_submissions(submission_states)
        self.session.commit()

    def _restore_submissions(self, submission_states: list[dict]) -> None:
        for state in submission_states:
            submission = self.session.get(KnowledgeSubmission, state["id"])
            if submission is None:
                continue
            for field, value in state.items():
                if field != "id":
                    setattr(submission, field, value)

    @staticmethod
    def _copy_version_values(version: DocumentVersion | None) -> dict | None:
        if version is None:
            return None
        return {
            "id": version.id,
            "version": version.version,
            "replaces_document_id": version.replaces_document_id,
            "source": version.source,
            "tags": list(version.tags or []),
            "category": version.category,
            "department": version.department,
            "expires_at": version.expires_at,
            "review_due_at": version.review_due_at,
            "last_reviewed_at": version.last_reviewed_at,
            "review_status": version.review_status,
            "created_at": version.created_at,
        }

    @staticmethod
    def _copy_submission_state(submission: KnowledgeSubmission) -> dict:
        return {
            "id": submission.id,
            "original_name": submission.original_name,
            "stored_name": submission.stored_name,
            "content_hash": submission.content_hash,
            "size_bytes": submission.size_bytes,
            "status": submission.status,
            "document_id": submission.document_id,
        }

    @staticmethod
    def _sync_published_submission(
        submission: KnowledgeSubmission, record: KnowledgeDocument
    ) -> None:
        submission.original_name = record.original_name
        submission.stored_name = record.stored_name
        submission.content_hash = record.content_hash
        submission.size_bytes = record.size_bytes
        submission.status = "published"
        submission.document_id = record.id

    @staticmethod
    def _build_replacement_version(
        record: KnowledgeDocument, old_values: dict | None
    ) -> DocumentVersion:
        values = old_values or {}
        return DocumentVersion(
            id=str(uuid4()),
            document_id=record.id,
            version=int(values.get("version") or 0) + 1,
            replaces_document_id=values.get("replaces_document_id"),
            source=values.get("source")
            or ("system" if record.is_system else "user_submission"),
            tags=list(values.get("tags") or []),
            category=values.get("category"),
            department=values.get("department"),
            expires_at=values.get("expires_at"),
            review_due_at=values.get("review_due_at"),
            last_reviewed_at=values.get("last_reviewed_at"),
            review_status=values.get("review_status") or "current",
        )

    @staticmethod
    def _source_type(
        record: KnowledgeDocument, version_values: dict | None
    ) -> str:
        if record.is_system:
            return "system"
        return str((version_values or {}).get("source") or "user_submission")

    @staticmethod
    def _copy_record(record: KnowledgeDocument) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=record.id,
            original_name=record.original_name,
            stored_name=record.stored_name,
            content_hash=record.content_hash,
            size_bytes=record.size_bytes,
            chunk_count=record.chunk_count,
            chunk_ids=list(record.chunk_ids),
            uploader_id=record.uploader_id,
            is_system=record.is_system,
            status=record.status,
            created_at=record.created_at,
        )

    async def _save_and_hash(self, upload_file: UploadFile, target: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        total_size = 0
        with target.open("wb") as output:
            while block := await upload_file.read(READ_BLOCK_SIZE):
                total_size += len(block)
                if total_size > self.settings.max_upload_size_bytes:
                    raise FileTooLargeError(
                        self.settings.max_upload_size_bytes // 1024 // 1024
                    )
                digest.update(block)
                output.write(block)
        if total_size == 0:
            raise DocumentParseError("上传文件为空")
        return digest.hexdigest(), total_size

    def _load_documents(self, path: Path, suffix: str) -> list[Document]:
        try:
            parsed = self.parser.parse_document(
                ParseRequest(path=path, suffix=suffix, file_name=path.name)
            )
            documents = self._parsed_to_documents(parsed)
        except Exception as exc:
            if isinstance(exc, DocumentParseError):
                raise
            raise DocumentParseError("无法解析文档，请确认文件内容和编码正确") from exc
        if not documents or not any(document.page_content.strip() for document in documents):
            raise DocumentParseError()
        return documents

    @staticmethod
    def _parsed_to_documents(parsed: ParsedDocument) -> list[Document]:
        documents: list[Document] = []
        for element in parsed.elements:
            content = DocumentLifecycleService._element_text(element)
            if not content.strip():
                continue
            metadata = {
                "element_id": element.element_id,
                "element_kind": element.kind,
            }
            if element.page_no is not None:
                metadata["page"] = element.page_no
            documents.append(Document(page_content=content, metadata=metadata))
        return documents

    @staticmethod
    def _element_text(element: ParsedElement) -> str:
        if element.kind == "title":
            return f"# {element.text}"
        if element.kind == "list":
            return f"- {element.text}"
        if element.kind == "table":
            return element.text
        return element.text

    def _split_documents(
        self,
        documents: list[Document],
        document_id: str,
        file_name: str,
        file_hash: str,
    ) -> list[Document]:
        for document in documents:
            document.metadata.update(
                {
                    "document_id": document_id,
                    "file_name": file_name,
                    "source": file_name,
                    "file_hash": file_hash,
                    "visibility": "public",
                    "document_type": Path(file_name).suffix.lower().lstrip("."),
                    "knowledge_base_version": self.settings.knowledge_base_version,
                }
            )
        chunks = []
        regular_documents = []
        for document in documents:
            if document.metadata.get("element_kind") == "table":
                chunks.extend(self._split_table_document(document))
            else:
                regular_documents.append(document)
        chunks.extend(
            chunk
            for chunk in self.splitter.split_documents(regular_documents)
            if chunk.page_content.strip()
        )
        if not chunks:
            raise DocumentParseError()
        return chunks

    def _split_table_document(self, document: Document) -> list[Document]:
        rows = [row.strip() for row in document.page_content.splitlines() if row.strip()]
        if not rows:
            return []
        if len(document.page_content) <= self.settings.chunk_size:
            return [document]
        header = rows[0]
        chunks: list[Document] = []
        current = header
        for row in rows[1:]:
            candidate = f"{current}\n{row}"
            if len(candidate) > self.settings.chunk_size and current != header:
                chunks.append(Document(page_content=current, metadata=dict(document.metadata)))
                current = f"{header}\n{row}"
            else:
                current = candidate
        if current.strip():
            chunks.append(Document(page_content=current, metadata=dict(document.metadata)))
        return chunks
