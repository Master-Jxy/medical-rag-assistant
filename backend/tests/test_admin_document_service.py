"""系统文档生命周期测试：创建、整体替换、删除与失败补偿。"""

import asyncio
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import DocumentBusyError, DocumentStoreError
from app.db.base import Base
from app.db.session import build_engine
from app.models import KnowledgeDocument
from app.modules.knowledge.repository import DocumentLockConflictError
from app.services.admin_document_service import AdminDocumentService
from tests.test_document_service import FakeVectorStore


def make_upload(name: str, text: str) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(text.encode()))


def build_admin_service(tmp_path):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "documents.json",
        chunk_size=30,
        chunk_overlap=5,
    )
    vector_store = FakeVectorStore()
    service = AdminDocumentService(session, settings=settings, vector_store=vector_store)
    return service, vector_store, session, engine


def test_admin_can_create_replace_and_delete_system_document(tmp_path) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        created = asyncio.run(
            service.create_system_document(make_upload("系统资料.txt", "第一版医学资料"))
        )
        old_ids = set(vector_store.entries)
        assert created.is_system is True and created.can_delete is True
        old_record = session.get(KnowledgeDocument, created.document_id)
        assert old_record is not None and old_record.uploader_id is None

        replaced = asyncio.run(
            service.replace_system_document(
                created.document_id, make_upload("系统资料新版.txt", "第二版医学资料")
            )
        )
        assert replaced.document_id != created.document_id
        assert session.get(KnowledgeDocument, created.document_id) is None
        assert session.get(KnowledgeDocument, replaced.document_id) is not None
        assert old_ids.isdisjoint(vector_store.entries)
        assert len(list(service.settings.upload_dir.glob("*.txt"))) == 1

        deleted = service.delete_system_document(replaced.document_id)
        assert deleted.document_id == replaced.document_id
        assert session.get(KnowledgeDocument, replaced.document_id) is None
        assert not vector_store.entries
        assert not list(service.settings.upload_dir.glob("*.txt"))
    finally:
        session.close()
        engine.dispose()


def test_replace_cleanup_failure_restores_old_database_file_and_vectors(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        created = asyncio.run(
            service.create_system_document(make_upload("稳定版.txt", "必须保留的旧资料"))
        )
        old_record = session.get(KnowledgeDocument, created.document_id)
        old_stored_name = old_record.stored_name
        old_ids = list(old_record.chunk_ids)
        original_delete = vector_store.delete_documents

        def fail_after_partial_old_delete(ids):
            if ids == old_ids:
                vector_store.entries.pop(ids[0], None)
                raise RuntimeError("模拟旧向量清理中断")
            original_delete(ids)

        monkeypatch.setattr(vector_store, "delete_documents", fail_after_partial_old_delete)
        with pytest.raises(DocumentStoreError):
            asyncio.run(
                service.replace_system_document(
                    created.document_id, make_upload("失败新版.txt", "无法完成的新资料")
                )
            )

        session.expire_all()
        restored = session.get(KnowledgeDocument, created.document_id)
        assert restored is not None and restored.stored_name == old_stored_name
        assert (service.settings.upload_dir / old_stored_name).is_file()
        assert set(old_ids) <= set(vector_store.entries)
        assert service.repository.count() == 1
        assert len(list(service.settings.upload_dir.glob("*.txt"))) == 1
    finally:
        session.close()
        engine.dispose()


def test_replace_database_switch_failure_removes_candidate_and_keeps_old(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        created = asyncio.run(
            service.create_system_document(make_upload("旧版.txt", "数据库失败也要保留"))
        )
        old_ids = set(vector_store.entries)
        old_path = next(service.settings.upload_dir.glob("*.txt"))

        monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError()))
        with pytest.raises(DocumentStoreError):
            asyncio.run(
                service.replace_system_document(
                    created.document_id, make_upload("候选版.txt", "候选内容")
                )
            )

        assert session.get(KnowledgeDocument, created.document_id) is not None
        assert old_path.is_file()
        assert set(vector_store.entries) == old_ids
        assert len(list(service.settings.upload_dir.glob("*.txt"))) == 1
    finally:
        session.close()
        engine.dispose()


def test_replace_lock_conflict_returns_busy_without_preparing_file(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        monkeypatch.setattr(
            service.repository,
            "get_by_id_for_update",
            lambda _document_id: (_ for _ in ()).throw(DocumentLockConflictError()),
        )
        with pytest.raises(DocumentBusyError):
            asyncio.run(
                service.replace_system_document("busy", make_upload("候选.txt", "内容"))
            )
        assert not vector_store.entries
        assert not service.settings.upload_dir.exists()
    finally:
        session.close()
        engine.dispose()


def test_replace_non_lock_database_error_is_not_misreported_as_busy(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        database_error = OperationalError("SELECT", {}, Exception("database offline"))
        monkeypatch.setattr(
            service.repository,
            "get_by_id_for_update",
            lambda _document_id: (_ for _ in ()).throw(database_error),
        )
        with pytest.raises(DocumentStoreError):
            asyncio.run(
                service.replace_system_document("offline", make_upload("候选.txt", "内容"))
            )
        assert not vector_store.entries
    finally:
        session.close()
        engine.dispose()
