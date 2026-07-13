"""文档上传业务：校验、保存、去重、解析、切分和向量入库。"""

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    DocumentParseError,
    DocumentNotFoundError,
    DocumentStoreError,
    DuplicateDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.infrastructure.vector_store import VectorStoreService
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)

ALLOWED_SUFFIXES = {".pdf", ".txt"}
READ_BLOCK_SIZE = 1024 * 1024


class DocumentService:
    """完成一次文档从 HTTP 文件到 Chroma 向量的完整入库。"""

    def __init__(
        self,
        settings: Settings | None = None,
        vector_store: VectorStoreService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStoreService(self.settings)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        )

    async def process_upload(self, upload_file: UploadFile) -> DocumentUploadResponse:
        """保存上传文件，确认不重复后解析、切分并写入 Chroma。"""
        original_name = Path(upload_file.filename or "").name
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise UnsupportedFileTypeError()

        self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
        document_id = str(uuid4())
        temporary_path = self.settings.upload_dir / f".{document_id}.uploading"
        final_path = self.settings.upload_dir / f"{document_id}{suffix}"

        try:
            file_hash, file_size = await self._save_and_hash(upload_file, temporary_path)
            if self._find_by_hash(file_hash) is not None:
                raise DuplicateDocumentError()

            documents = self._load_documents(temporary_path, suffix)
            chunks = self._split_documents(documents, document_id, original_name, file_hash)
            chunk_ids = [f"{document_id}:{index}" for index in range(len(chunks))]

            self.vector_store.add_documents(chunks, chunk_ids)
            temporary_path.replace(final_path)

            created_at = datetime.now(timezone.utc)
            record = {
                "document_id": document_id,
                "file_name": original_name,
                "stored_name": final_path.name,
                "file_hash": file_hash,
                "file_size": file_size,
                "chunk_count": len(chunks),
                "chunk_ids": chunk_ids,
                "status": "ready",
                "created_at": created_at.isoformat(),
            }
            self._append_record(record)
            return DocumentUploadResponse(**record)
        except (UnsupportedFileTypeError, FileTooLargeError, DuplicateDocumentError, DocumentParseError):
            raise
        except Exception as exc:
            # 使用可预测的片段 ID 回滚，防止半次入库留下脏向量。
            chunk_ids = locals().get("chunk_ids", [])
            try:
                self.vector_store.delete_documents(chunk_ids)
            except Exception:
                pass
            final_path.unlink(missing_ok=True)
            raise DocumentStoreError() from exc
        finally:
            temporary_path.unlink(missing_ok=True)
            await upload_file.close()

    def list_documents(self) -> DocumentListResponse:
        """按最新上传时间优先返回登记表中的文档。"""
        records = sorted(
            self._read_registry(),
            key=lambda record: record.get("created_at", ""),
            reverse=True,
        )
        documents = [DocumentItem(**record) for record in records]
        return DocumentListResponse(documents=documents, total=len(documents))

    def delete_document(self, document_id: str) -> DocumentDeleteResponse:
        """同步删除 Chroma 片段、原始文件和登记记录。"""
        records = self._read_registry()
        record = next(
            (item for item in records if item.get("document_id") == document_id),
            None,
        )
        if record is None:
            raise DocumentNotFoundError()

        try:
            self.vector_store.delete_documents(record.get("chunk_ids", []))
            stored_path = self.settings.upload_dir / record["stored_name"]
            stored_path.unlink(missing_ok=True)
            remaining_records = [
                item for item in records if item.get("document_id") != document_id
            ]
            self._write_registry(remaining_records)
            return DocumentDeleteResponse(document_id=document_id)
        except DocumentNotFoundError:
            raise
        except Exception as exc:
            raise DocumentStoreError() from exc

    async def _save_and_hash(self, upload_file: UploadFile, target: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        total_size = 0
        with target.open("wb") as output:
            while block := await upload_file.read(READ_BLOCK_SIZE):
                total_size += len(block)
                if total_size > self.settings.max_upload_size_bytes:
                    raise FileTooLargeError(self.settings.max_upload_size_bytes // 1024 // 1024)
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
                text = path.read_text(encoding="utf-8")
                documents = [Document(page_content=text)]
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
                }
            )
        chunks = [chunk for chunk in self.splitter.split_documents(documents) if chunk.page_content.strip()]
        if not chunks:
            raise DocumentParseError()
        return chunks

    def _read_registry(self) -> list[dict]:
        path = self.settings.document_registry_path
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DocumentStoreError() from exc

    def _find_by_hash(self, file_hash: str) -> dict | None:
        return next(
            (record for record in self._read_registry() if record.get("file_hash") == file_hash),
            None,
        )

    def _append_record(self, record: dict) -> None:
        records = self._read_registry()
        records.append(record)
        self._write_registry(records)

    def _write_registry(self, records: list[dict]) -> None:
        """先写临时文件再替换，避免写到一半破坏登记表。"""
        path = self.settings.document_registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)


@lru_cache
def get_document_service() -> DocumentService:
    """复用 Chroma 连接和文本切分器。"""
    return DocumentService()
