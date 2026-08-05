"""文档服务测试：验证 MySQL 登记边界、权限和三处存储回滚，不调用外部模型。"""

import asyncio
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from langchain_core.documents import Document
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    DocumentDeleteForbiddenError,
    DocumentNotFoundError,
    DocumentStoreError,
    DuplicateDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.db.base import Base
from app.db.session import build_engine
from app.models import KnowledgeDocument, User
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.services.document_service import DocumentService


class FakeVectorStore:
    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}
        self.added_documents = []
        self.added_ids = []
        self.deleted_ids = []
        self.restore_calls = 0

    def add_documents(self, documents, ids) -> None:
        self.added_documents.extend(documents)
        self.added_ids.extend(ids)
        for chunk_id, document in zip(ids, documents, strict=True):
            self.entries[chunk_id] = {
                "document": document.page_content,
                "metadata": document.metadata,
                "embedding": [0.1, 0.2],
            }

    def snapshot_documents(self, ids) -> dict:
        existing = [chunk_id for chunk_id in ids if chunk_id in self.entries]
        return {
            "ids": existing,
            "documents": [self.entries[item]["document"] for item in existing],
            "metadatas": [self.entries[item]["metadata"] for item in existing],
            "embeddings": [self.entries[item]["embedding"] for item in existing],
        }

    def delete_documents(self, ids) -> None:
        self.deleted_ids.extend(ids)
        for chunk_id in ids:
            self.entries.pop(chunk_id, None)

    def restore_documents(self, snapshot) -> None:
        self.restore_calls += 1
        for index, chunk_id in enumerate(snapshot["ids"]):
            self.entries[chunk_id] = {
                "document": snapshot["documents"][index],
                "metadata": snapshot["metadatas"][index],
                "embedding": snapshot["embeddings"][index],
            }


def build_service(tmp_path, *, max_size: int = 1024 * 1024):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    owner = User(
        id="document-owner",
        email="document-owner@example.com",
        password_hash="not-used",
    )
    other = User(
        id="document-other",
        email="document-other@example.com",
        password_hash="not-used",
    )
    session.add_all([owner, other])
    session.commit()
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_asset_dir=tmp_path / "assets",
        document_registry_path=tmp_path / "documents.json",
        max_upload_size_bytes=max_size,
        chunk_size=30,
        chunk_overlap=5,
    )
    vector_store = FakeVectorStore()
    service = DocumentService(
        session=session, settings=settings, vector_store=vector_store
    )
    return service, vector_store, session, engine, owner, other


def make_upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


def test_table_documents_are_split_by_rows_with_repeated_header(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "documents.json",
        chunk_size=24,
        chunk_overlap=0,
    )
    service = DocumentLifecycleService(None, settings, FakeVectorStore())
    table = Document(
        page_content="Name | Value\nalpha | 1111111111\nbeta | 2222222222",
        metadata={"element_kind": "table", "page": 2},
    )

    chunks = service._split_documents(
        [table],
        document_id="doc-table",
        file_name="complex.pdf",
        file_hash="c" * 64,
    )

    assert len(chunks) == 2
    assert all(chunk.page_content.startswith("Name | Value") for chunk in chunks)
    assert all(chunk.metadata["page"] == 2 for chunk in chunks)
    assert all(chunk.metadata["document_type"] == "pdf" for chunk in chunks)


def test_txt_upload_is_saved_split_and_registered_in_mysql(tmp_path) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        result = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("高血压资料.txt", "高血压管理需要定期监测血压。".encode()),
            )
        )

        saved = session.get(KnowledgeDocument, result.document_id)
        assert result.file_name == "高血压资料.txt"
        assert result.is_system is False
        assert result.can_delete is False
        assert saved is not None and saved.uploader_id == owner.id
        assert len(vector_store.added_documents) == result.chunk_count
        assert vector_store.added_documents[0].metadata["visibility"] == "public"
        assert vector_store.added_documents[0].metadata["document_type"] == "txt"
        assert (
            vector_store.added_documents[0].metadata["knowledge_base_version"]
            == "live_v1"
        )
        assert vector_store.added_documents[0].metadata["chunk_id"].endswith(":0")
        assert len(list((tmp_path / "uploads").glob("*.txt"))) == 1
        assert not (tmp_path / "documents.json").exists()
    finally:
        session.close()
        engine.dispose()


def test_lifecycle_delete_removes_document_asset_sidecars(tmp_path) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("asset-cleanup.txt", "asset cleanup content".encode()),
            )
        )
        record = session.get(KnowledgeDocument, uploaded.document_id)
        chunk_ids = list(record.chunk_ids)
        asset_dir = service.settings.document_asset_dir / "documents" / record.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")

        deleted_id = service.lifecycle.delete_document(record)

        assert deleted_id == uploaded.document_id
        assert not asset_dir.exists()
        assert set(vector_store.deleted_ids) == set(chunk_ids)
    finally:
        session.close()
        engine.dispose()


def test_lifecycle_delete_commit_failure_restores_staged_assets(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("asset-restore.txt", "asset restore content".encode()),
            )
        )
        record = session.get(KnowledgeDocument, uploaded.document_id)
        asset_dir = service.settings.document_asset_dir / "documents" / record.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")
        original_commit = session.commit

        def fail_delete_commit_once():
            monkeypatch.setattr(session, "commit", original_commit)
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(session, "commit", fail_delete_commit_once)

        with pytest.raises(DocumentStoreError):
            service.lifecycle.delete_document(record)

        assert asset_dir.is_dir()
        assert (asset_dir / "asset.txt").is_file()
        assert session.get(KnowledgeDocument, uploaded.document_id) is not None
        assert set(vector_store.entries)
    finally:
        session.close()
        engine.dispose()


def test_lifecycle_delete_post_commit_asset_cleanup_failure_marks_pending(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("asset-pending.txt", "asset pending content".encode()),
            )
        )
        record = session.get(KnowledgeDocument, uploaded.document_id)
        chunk_ids = set(record.chunk_ids)
        asset_dir = service.settings.document_asset_dir / "documents" / record.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")
        original_rmtree = shutil.rmtree

        def fail_trash_rmtree(path):
            if ".trash" in Path(path).parts:
                raise OSError("simulated post-commit cleanup failure")
            return original_rmtree(path)

        monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_trash_rmtree)

        deleted_id = service.lifecycle.delete_document(record)

        assert deleted_id == uploaded.document_id
        assert session.get(KnowledgeDocument, uploaded.document_id) is None
        assert not asset_dir.exists()
        assert chunk_ids.issubset(set(vector_store.deleted_ids))
        assert vector_store.restore_calls == 0
        markers = list((service.settings.document_asset_dir / ".cleanup_pending").glob("*.json"))
        assert len(markers) == 1
        assert list((service.settings.document_asset_dir / ".trash" / "documents").glob("*"))

        monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", original_rmtree)
        assert service.lifecycle.asset_store.retry_pending_cleanups() == 1
        assert not markers[0].exists()
        assert not list((service.settings.document_asset_dir / ".trash" / "documents").glob("*"))
    finally:
        session.close()
        engine.dispose()


def test_lifecycle_delete_marker_write_failure_still_returns_success(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("asset-marker-fail.txt", "asset marker failure".encode()),
            )
        )
        record = session.get(KnowledgeDocument, uploaded.document_id)
        chunk_ids = set(record.chunk_ids)
        asset_dir = service.settings.document_asset_dir / "documents" / record.id
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")
        original_rmtree = shutil.rmtree

        def fail_trash_rmtree(path):
            if ".trash" in Path(path).parts:
                raise OSError("simulated post-commit cleanup failure")
            return original_rmtree(path)

        def fail_mark_cleanup_pending(self, staged, *, reason):
            del self, staged, reason
            raise OSError("simulated marker write failure")

        monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_trash_rmtree)
        monkeypatch.setattr(
            "app.modules.knowledge.asset_storage.ControlledDocumentAssetStore.mark_cleanup_pending",
            fail_mark_cleanup_pending,
        )

        deleted_id = service.lifecycle.delete_document(record)

        assert deleted_id == uploaded.document_id
        assert session.get(KnowledgeDocument, uploaded.document_id) is None
        assert not asset_dir.exists()
        assert chunk_ids.issubset(set(vector_store.deleted_ids))
        assert vector_store.restore_calls == 0
        assert not list((service.settings.document_asset_dir / ".cleanup_pending").glob("*.json"))
        assert list((service.settings.document_asset_dir / ".trash" / "documents").glob("*"))
    finally:
        session.close()
        engine.dispose()


def test_duplicate_content_is_rejected_before_second_embedding(tmp_path) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        content = "相同内容不能重复向量化。".encode()
        asyncio.run(service.process_upload(owner.id, make_upload("资料一.txt", content)))
        first_ids = list(vector_store.added_ids)

        with pytest.raises(DuplicateDocumentError):
            asyncio.run(service.process_upload(owner.id, make_upload("资料二.txt", content)))

        assert vector_store.added_ids == first_ids
        assert session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1
    finally:
        session.close()
        engine.dispose()


def test_unsupported_and_oversized_files_are_rejected(tmp_path) -> None:
    service, vector_store, session, engine, owner, _ = build_service(
        tmp_path, max_size=5
    )
    try:
        with pytest.raises(UnsupportedFileTypeError):
            asyncio.run(
                service.process_upload(owner.id, make_upload("恶意程序.exe", b"content"))
            )
        with pytest.raises(FileTooLargeError):
            asyncio.run(
                service.process_upload(owner.id, make_upload("过大.txt", b"123456"))
            )
        assert not vector_store.added_ids
    finally:
        session.close()
        engine.dispose()


def test_public_list_and_delete_permissions(tmp_path) -> None:
    service, vector_store, session, engine, owner, other = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id, make_upload("待删除.txt", "需要同步删除的内容。".encode())
            )
        )

        owner_item = service.list_documents(owner.id).documents[0]
        other_item = service.list_documents(other.id).documents[0]
        assert owner_item.can_delete is False
        assert other_item.can_delete is False

        with pytest.raises(DocumentDeleteForbiddenError):
            service.delete_document(other.id, uploaded.document_id)

        with pytest.raises(DocumentDeleteForbiddenError):
            service.delete_document(owner.id, uploaded.document_id)
        assert not vector_store.deleted_ids
        assert service.list_documents(owner.id).total == 1
        assert list((tmp_path / "uploads").glob("*.txt"))
    finally:
        session.close()
        engine.dispose()


def test_system_document_cannot_be_deleted_by_normal_user(tmp_path) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        stored_path = service.settings.upload_dir / "system.txt"
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_text("系统资料", encoding="utf-8")
        record = KnowledgeDocument(
            id="system-document",
            original_name="系统资料.txt",
            stored_name="system.txt",
            content_hash="a" * 64,
            size_bytes=12,
            chunk_count=1,
            chunk_ids=["system-document:0"],
            uploader_id=None,
            is_system=True,
            status="ready",
        )
        session.add(record)
        session.commit()
        vector_store.entries["system-document:0"] = {
            "document": "系统资料",
            "metadata": {"document_id": "system-document"},
            "embedding": [0.1, 0.2],
        }

        listed = service.list_documents(owner.id).documents[0]
        assert listed.is_system is True and listed.can_delete is False
        with pytest.raises(DocumentDeleteForbiddenError):
            service.delete_document(owner.id, record.id)
        assert stored_path.exists()
        assert session.get(KnowledgeDocument, record.id) is not None
        assert "system-document:0" in vector_store.entries
    finally:
        session.close()
        engine.dispose()


def test_delete_database_failure_restores_file_and_vector_snapshot(tmp_path) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id, make_upload("回滚.txt", "删除失败必须恢复。".encode())
            )
        )
        original_ids = set(vector_store.entries)
        stored_path = next((tmp_path / "uploads").glob("*.txt"))

        def fail_delete(_record):
            raise RuntimeError("模拟数据库删除失败")

        service.repository.delete = fail_delete
        with pytest.raises(DocumentDeleteForbiddenError):
            service.delete_document(owner.id, uploaded.document_id)

        assert stored_path.exists()
        assert set(vector_store.entries) == original_ids
        assert vector_store.restore_calls == 0
        assert session.get(KnowledgeDocument, uploaded.document_id) is not None
    finally:
        session.close()
        engine.dispose()


def test_upload_database_failure_removes_new_file_and_vectors(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        def fail_commit():
            raise RuntimeError("模拟数据库写入失败")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(DocumentStoreError):
            asyncio.run(
                service.process_upload(
                    owner.id, make_upload("写入回滚.txt", "必须完整回滚".encode())
                )
            )

        assert not vector_store.entries
        assert vector_store.deleted_ids == vector_store.added_ids
        assert not list((tmp_path / "uploads").glob("*.txt"))
        assert session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 0
    finally:
        session.close()
        engine.dispose()


def test_delete_unknown_document_returns_not_found(tmp_path) -> None:
    service, _, session, engine, owner, _ = build_service(tmp_path)
    try:
        with pytest.raises(DocumentNotFoundError):
            service.delete_document(owner.id, "missing-document-id")
    finally:
        session.close()
        engine.dispose()


def test_reference_pdf_can_be_parsed_without_embedding(tmp_path) -> None:
    service, _, session, engine, _, _ = build_service(tmp_path)
    try:
        project_root = Path(__file__).resolve().parents[2]
        pdf_path = (
            project_root
            / "reference"
            / "original-rag-agent"
            / "data"
            / "扫地机器人100问.pdf"
        )
        documents = service._load_documents(pdf_path, ".pdf")
        assert documents
        assert any(document.page_content.strip() for document in documents)
        assert "page" in documents[0].metadata
    finally:
        session.close()
        engine.dispose()


def test_html_replacement_database_failure_restores_old_file_and_vectors(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("原始.txt", "原始资料内容。".encode()),
            )
        )
        old_record = session.get(KnowledgeDocument, uploaded.document_id)
        old_path = service.settings.upload_dir / old_record.stored_name
        old_ids = set(vector_store.entries)

        def fail_commit_once():
            raise RuntimeError("模拟替换数据库失败")

        monkeypatch.setattr(session, "commit", fail_commit_once)
        with pytest.raises(DocumentStoreError):
            asyncio.run(
                service.lifecycle.replace_document(
                    uploaded.document_id,
                    make_upload(
                        "替换.html",
                        "<html><body><h1>替换标题</h1><p>替换内容</p></body></html>".encode(),
                    ),
                    actor_user_id=owner.id,
                )
            )

        assert old_path.exists()
        assert set(vector_store.entries) == old_ids
        assert session.get(KnowledgeDocument, uploaded.document_id) is not None
    finally:
        session.close()
        engine.dispose()


def test_replace_post_commit_old_asset_cleanup_failure_marks_pending(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("old-asset.txt", "old asset document content".encode()),
            )
        )
        old_record = session.get(KnowledgeDocument, uploaded.document_id)
        old_asset_dir = service.settings.document_asset_dir / "documents" / old_record.id
        old_asset_dir.mkdir(parents=True, exist_ok=True)
        (old_asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")
        original_rmtree = shutil.rmtree

        def fail_trash_rmtree(path):
            if ".trash" in Path(path).parts:
                raise OSError("simulated replace cleanup failure")
            return original_rmtree(path)

        monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_trash_rmtree)

        replacement = asyncio.run(
            service.lifecycle.replace_document(
                uploaded.document_id,
                make_upload("new-asset.txt", "new asset document content".encode()),
                actor_user_id=owner.id,
            )
        )

        assert replacement.id != uploaded.document_id
        assert session.get(KnowledgeDocument, uploaded.document_id) is None
        assert session.get(KnowledgeDocument, replacement.id) is not None
        assert not old_asset_dir.exists()
        assert vector_store.restore_calls == 0
        assert list((service.settings.document_asset_dir / ".cleanup_pending").glob("*.json"))
        assert list((service.settings.document_asset_dir / ".trash" / "documents").glob("*"))
    finally:
        session.close()
        engine.dispose()


def test_replace_marker_write_failure_still_returns_success(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine, owner, _ = build_service(tmp_path)
    try:
        uploaded = asyncio.run(
            service.process_upload(
                owner.id,
                make_upload("old-marker.txt", "old marker document content".encode()),
            )
        )
        old_record = session.get(KnowledgeDocument, uploaded.document_id)
        old_asset_dir = service.settings.document_asset_dir / "documents" / old_record.id
        old_asset_dir.mkdir(parents=True, exist_ok=True)
        (old_asset_dir / "asset.txt").write_text("sidecar", encoding="utf-8")
        original_rmtree = shutil.rmtree

        def fail_trash_rmtree(path):
            if ".trash" in Path(path).parts:
                raise OSError("simulated replace cleanup failure")
            return original_rmtree(path)

        def fail_mark_cleanup_pending(self, staged, *, reason):
            del self, staged, reason
            raise OSError("simulated marker write failure")

        monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_trash_rmtree)
        monkeypatch.setattr(
            "app.modules.knowledge.asset_storage.ControlledDocumentAssetStore.mark_cleanup_pending",
            fail_mark_cleanup_pending,
        )

        replacement = asyncio.run(
            service.lifecycle.replace_document(
                uploaded.document_id,
                make_upload("new-marker.txt", "new marker document content".encode()),
                actor_user_id=owner.id,
            )
        )

        assert replacement.id != uploaded.document_id
        assert session.get(KnowledgeDocument, uploaded.document_id) is None
        assert session.get(KnowledgeDocument, replacement.id) is not None
        assert not old_asset_dir.exists()
        assert vector_store.restore_calls == 0
        assert not list((service.settings.document_asset_dir / ".cleanup_pending").glob("*.json"))
        assert list((service.settings.document_asset_dir / ".trash" / "documents").glob("*"))
    finally:
        session.close()
        engine.dispose()
