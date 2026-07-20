"""文档在 MySQL、文件系统与 Chroma 之间的共享生命周期。"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
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
    SystemDocumentRequiredError,
    UnsupportedFileTypeError,
)
from app.infrastructure.vector_store import VectorStoreService
from app.modules.knowledge.models import KnowledgeDocument
from app.modules.knowledge.repository import (
    DocumentLockConflictError,
    DocumentRepository,
)

ALLOWED_SUFFIXES = {".pdf", ".txt"}
READ_BLOCK_SIZE = 1024 * 1024


@dataclass
class PreparedDocument:
    record: KnowledgeDocument
    final_path: Path
    chunk_ids: list[str]
    vectors_added: bool = True


class DocumentLifecycleService:
    """集中实现跨三处存储的创建、删除和系统文档整体替换。"""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        vector_store: VectorStoreService,
        repository: DocumentRepository | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.vector_store = vector_store
        self.repository = repository or DocumentRepository(session)
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

        try:
            snapshot = self.vector_store.snapshot_documents(record.chunk_ids)
            if set(snapshot.get("ids") or []) != set(record.chunk_ids):
                raise DocumentStoreError()
            if not stored_path.is_file():
                raise DocumentStoreError()

            stored_path.replace(tombstone_path)
            file_moved = True
            delete_started = True
            self.vector_store.delete_documents(record.chunk_ids)
            self.repository.delete(record)
            self.session.commit()
            try:
                tombstone_path.unlink(missing_ok=True)
            except OSError:
                pass
            return record.id
        except DocumentStoreError:
            self.session.rollback()
            self._restore_delete(
                stored_path, tombstone_path, snapshot, file_moved, delete_started
            )
            raise
        except Exception as exc:
            self.session.rollback()
            try:
                self._restore_delete(
                    stored_path, tombstone_path, snapshot, file_moved, delete_started
                )
            except Exception:
                pass
            raise DocumentStoreError() from exc

    async def replace_system_document(
        self, document_id: str, upload_file: UploadFile
    ) -> KnowledgeDocument:
        prepared: PreparedDocument | None = None
        old_snapshot: dict | None = None
        old_record: KnowledgeDocument | None = None
        old_copy: KnowledgeDocument | None = None
        switched = False
        old_file_moved = False
        old_delete_started = False
        tombstone_path: Path | None = None

        try:
            try:
                old_record = self.repository.get_by_id_for_update(document_id)
            except DocumentLockConflictError as exc:
                self.session.rollback()
                raise DocumentBusyError() from exc
            if old_record is None:
                raise DocumentNotFoundError()
            if not old_record.is_system:
                raise SystemDocumentRequiredError()

            old_copy = self._copy_record(old_record)
            old_path = self.settings.upload_dir / old_record.stored_name
            tombstone_path = self.settings.upload_dir / f".{old_record.stored_name}.replacing"
            if not old_path.is_file():
                raise DocumentStoreError()
            old_snapshot = self.vector_store.snapshot_documents(old_record.chunk_ids)
            if set(old_snapshot.get("ids") or []) != set(old_record.chunk_ids):
                raise DocumentStoreError()

            prepared = await self._prepare_upload(
                upload_file, uploader_id=None, is_system=True
            )
            self.repository.delete(old_record)
            self.repository.add(prepared.record)
            self.session.commit()
            switched = True

            old_path.replace(tombstone_path)
            old_file_moved = True
            old_delete_started = True
            self.vector_store.delete_documents(old_record.chunk_ids)
            tombstone_path.unlink(missing_ok=True)
            self.session.refresh(prepared.record)
            return prepared.record
        except (
            DocumentNotFoundError,
            SystemDocumentRequiredError,
            DocumentBusyError,
            UnsupportedFileTypeError,
            FileTooLargeError,
            DuplicateDocumentError,
            DocumentParseError,
        ):
            self.session.rollback()
            if prepared is not None and not switched:
                self._cleanup_prepared(prepared)
            raise
        except IntegrityError as exc:
            self.session.rollback()
            if prepared is not None and not switched:
                self._cleanup_prepared(prepared)
            raise DuplicateDocumentError() from exc
        except Exception as exc:
            self.session.rollback()
            if switched and prepared is not None and old_copy is not None:
                self._rollback_replacement(
                    prepared,
                    old_copy,
                    old_snapshot,
                    tombstone_path,
                    old_file_moved,
                    old_delete_started,
                )
            elif prepared is not None:
                self._cleanup_prepared(prepared)
            raise DocumentStoreError() from exc
        finally:
            await upload_file.close()

    async def _prepare_upload(
        self,
        upload_file: UploadFile,
        *,
        uploader_id: str | None,
        is_system: bool,
    ) -> PreparedDocument:
        original_name = Path(upload_file.filename or "").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise UnsupportedFileTypeError()

        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        document_id = str(uuid4())
        temporary_path = self.settings.upload_dir / f".{document_id}.uploading"
        final_path = self.settings.upload_dir / f"{document_id}{suffix}"
        chunk_ids: list[str] = []
        vectors_added = False
        try:
            file_hash, file_size = await self._save_and_hash(upload_file, temporary_path)
            if self.repository.get_by_hash(file_hash) is not None:
                raise DuplicateDocumentError()
            documents = self._load_documents(temporary_path, suffix)
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
                status="ready",
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

    def _rollback_replacement(
        self,
        prepared: PreparedDocument,
        old_record: KnowledgeDocument,
        old_snapshot: dict | None,
        tombstone_path: Path | None,
        old_file_moved: bool,
        old_delete_started: bool,
    ) -> None:
        old_path = self.settings.upload_dir / old_record.stored_name
        if old_delete_started and old_snapshot is not None:
            self.vector_store.restore_documents(old_snapshot)
        if old_file_moved and tombstone_path is not None and tombstone_path.exists():
            tombstone_path.replace(old_path)

        current = self.repository.get_by_id(prepared.record.id)
        if current is not None:
            self.repository.delete(current)
        self.repository.add(old_record)
        self.session.commit()
        self._cleanup_prepared(prepared)

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
            if suffix == ".pdf":
                documents = PyPDFLoader(str(path)).load()
            else:
                documents = [Document(page_content=path.read_text(encoding="utf-8"))]
        except Exception as exc:
            raise DocumentParseError("无法解析文档，请确认文件内容和编码正确") from exc
        if not documents or not any(document.page_content.strip() for document in documents):
            raise DocumentParseError()
        return documents

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
        chunks = [
            chunk
            for chunk in self.splitter.split_documents(documents)
            if chunk.page_content.strip()
        ]
        if not chunks:
            raise DocumentParseError()
        return chunks
