"""文档服务测试：真实执行保存、哈希、解析和切分，但不调用外部模型。"""

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.services.document_service import DocumentService


class FakeVectorStore:
    def __init__(self) -> None:
        self.added_documents = []
        self.added_ids = []
        self.deleted_ids = []

    def add_documents(self, documents, ids) -> None:
        self.added_documents.extend(documents)
        self.added_ids.extend(ids)

    def delete_documents(self, ids) -> None:
        self.deleted_ids.extend(ids)


def build_service(tmp_path, *, max_size: int = 1024 * 1024):
    settings = Settings(
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "documents.json",
        max_upload_size_bytes=max_size,
        chunk_size=30,
        chunk_overlap=5,
    )
    vector_store = FakeVectorStore()
    return DocumentService(settings=settings, vector_store=vector_store), vector_store


def make_upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


def test_txt_upload_is_saved_split_and_registered(tmp_path) -> None:
    service, vector_store = build_service(tmp_path)
    upload = make_upload("高血压资料.txt", "高血压管理需要定期监测血压。".encode())

    result = asyncio.run(service.process_upload(upload))

    assert result.file_name == "高血压资料.txt"
    assert result.status == "ready"
    assert result.chunk_count >= 1
    assert len(vector_store.added_documents) == result.chunk_count
    assert vector_store.added_documents[0].metadata["document_id"] == result.document_id
    assert (tmp_path / "documents.json").exists()
    assert len(list((tmp_path / "uploads").glob("*.txt"))) == 1


def test_duplicate_content_is_rejected_before_second_embedding(tmp_path) -> None:
    service, vector_store = build_service(tmp_path)
    content = "相同内容不能重复向量化。".encode()
    asyncio.run(service.process_upload(make_upload("资料一.txt", content)))

    with pytest.raises(DuplicateDocumentError):
        asyncio.run(service.process_upload(make_upload("资料二.txt", content)))

    assert len(vector_store.added_ids) == 1


def test_unsupported_file_type_is_rejected(tmp_path) -> None:
    service, _ = build_service(tmp_path)

    with pytest.raises(UnsupportedFileTypeError):
        asyncio.run(service.process_upload(make_upload("恶意程序.exe", b"content")))


def test_oversized_file_is_rejected(tmp_path) -> None:
    service, vector_store = build_service(tmp_path, max_size=5)

    with pytest.raises(FileTooLargeError):
        asyncio.run(service.process_upload(make_upload("过大.txt", b"123456")))

    assert not vector_store.added_ids


def test_list_and_delete_document_remove_all_three_storage_locations(tmp_path) -> None:
    service, vector_store = build_service(tmp_path)
    uploaded = asyncio.run(
        service.process_upload(make_upload("待删除.txt", "需要同步删除的内容。".encode()))
    )

    listed = service.list_documents()
    assert listed.total == 1
    assert listed.documents[0].document_id == uploaded.document_id

    result = service.delete_document(uploaded.document_id)

    assert result.document_id == uploaded.document_id
    assert vector_store.deleted_ids == vector_store.added_ids
    assert service.list_documents().total == 0
    assert not list((tmp_path / "uploads").glob("*.txt"))


def test_delete_unknown_document_returns_not_found(tmp_path) -> None:
    service, _ = build_service(tmp_path)

    with pytest.raises(DocumentNotFoundError):
        service.delete_document("missing-document-id")


def test_reference_pdf_can_be_parsed_without_embedding(tmp_path) -> None:
    """使用仓库内现有 PDF 验证真实解析器，本测试不会向量化或调用模型。"""
    service, _ = build_service(tmp_path)
    project_root = Path(__file__).resolve().parents[2]
    pdf_path = project_root / "reference" / "original-rag-agent" / "data" / "扫地机器人100问.pdf"

    documents = service._load_documents(pdf_path, ".pdf")

    assert documents
    assert any(document.page_content.strip() for document in documents)
    assert "page" in documents[0].metadata
