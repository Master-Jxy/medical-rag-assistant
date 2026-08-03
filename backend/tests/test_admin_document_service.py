"""系统文档生命周期测试：创建、整体替换、删除与失败补偿。"""

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import DocumentBusyError, DocumentStoreError
from app.db.base import Base
from app.db.session import build_engine
from app.models import AuditEvent, DocumentVersion, KnowledgeDocument, KnowledgeSubmission, User
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.knowledge.parser import ParsedPreview
from app.modules.knowledge.repository import DocumentLockConflictError
from app.modules.knowledge.submission_service import KnowledgeSubmissionService
from app.services.admin_document_service import AdminDocumentService
from tests.test_document_service import FakeVectorStore


def make_upload(name: str, text: str) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(text.encode()))


class FakeSubmissionParser:
    def parse(self, _path, _suffix):
        return ParsedPreview("重新提交预览", 1)


def build_admin_service(tmp_path):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path / "uploads",
        document_registry_path=tmp_path / "documents.json",
        submission_dir=tmp_path / "submissions",
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
        linked_submission = KnowledgeSubmission(
            id="legacy-system-submission",
            submitter_id=None,
            original_name=old_record.original_name,
            stored_name=old_record.stored_name,
            content_hash=old_record.content_hash,
            size_bytes=old_record.size_bytes,
            status="published",
            parse_warnings=[],
            document_id=old_record.id,
        )
        session.add(linked_submission)
        session.commit()

        replaced = asyncio.run(
            service.replace_system_document(
                created.document_id, make_upload("系统资料新版.txt", "第二版医学资料")
            )
        )
        assert replaced.document_id != created.document_id
        assert session.get(KnowledgeDocument, created.document_id) is None
        assert session.get(KnowledgeDocument, replaced.document_id) is not None
        session.refresh(linked_submission)
        replacement_record = session.get(KnowledgeDocument, replaced.document_id)
        assert linked_submission.document_id == replaced.document_id
        assert linked_submission.content_hash == replacement_record.content_hash
        assert linked_submission.original_name == replacement_record.original_name
        assert old_ids.isdisjoint(vector_store.entries)
        assert len(list(service.settings.upload_dir.glob("*.txt"))) == 1

        deleted = service.delete_system_document(replaced.document_id)
        assert deleted.document_id == replaced.document_id
        assert session.get(KnowledgeDocument, replaced.document_id) is None
        session.refresh(linked_submission)
        assert linked_submission.status == "archived"
        assert linked_submission.document_id is None
        assert not vector_store.entries
        assert not list(service.settings.upload_dir.glob("*.txt"))

        session.add(
            User(
                id="new-submitter",
                email="new-submitter@example.com",
                password_hash="hash",
            )
        )
        session.commit()
        resubmitted = asyncio.run(
            KnowledgeSubmissionService(
                session,
                service.settings,
                FakeSubmissionParser(),
            ).submit(
                "new-submitter",
                make_upload("系统资料重新提交.txt", "第二版医学资料（重新整理）"),
            )
        )
        assert resubmitted.status == "pending_review"
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
        linked_submission = KnowledgeSubmission(
            id="replace-failure-submission",
            submitter_id=None,
            original_name=old_record.original_name,
            stored_name=old_record.stored_name,
            content_hash=old_record.content_hash,
            size_bytes=old_record.size_bytes,
            status="published",
            parse_warnings=[],
            document_id=old_record.id,
        )
        session.add(linked_submission)
        session.commit()
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
        session.refresh(linked_submission)
        assert linked_submission.status == "published"
        assert linked_submission.document_id == created.document_id
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
        with pytest.raises(DocumentBusyError) as exc_info:
            asyncio.run(
                service.replace_system_document("busy", make_upload("候选.txt", "内容"))
            )
        assert exc_info.value.status_code == 409
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


def test_admin_replaces_user_asset_and_preserves_provenance_and_governance(tmp_path) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        owner = User(id="asset-owner", email="asset-owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        old = asyncio.run(
            service.lifecycle.create_document(
                make_upload("用户原稿.txt", "用户审核发布的原始资料"),
                uploader_id=owner.id,
                is_system=False,
            )
        )
        now = datetime.now(timezone.utc)
        version = DocumentVersion(
            id="user-version",
            document_id=old.id,
            version=3,
            source="user_submission",
            tags=["心血管", "指南"],
            category="诊疗规范",
            department="心内科",
            expires_at=now + timedelta(days=365),
            review_due_at=now + timedelta(days=90),
            last_reviewed_at=now,
            review_status="in_review",
        )
        submission = KnowledgeSubmission(
            id="user-submission",
            submitter_id=owner.id,
            original_name=old.original_name,
            stored_name=old.stored_name,
            content_hash=old.content_hash,
            size_bytes=old.size_bytes,
            status="published",
            parse_warnings=[],
            document_id=old.id,
        )
        session.add_all([version, submission])
        session.commit()

        service.audit = SqlAlchemyAuditRecorder(session)
        replaced = asyncio.run(
            service.replace_document(
                old.id,
                make_upload("用户新版.txt", "替换后的完整用户资料"),
                actor_user_id="admin-user",
                request_id="replace-request",
            )
        )

        new_record = session.get(KnowledgeDocument, replaced.document_id)
        new_version = session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == replaced.document_id)
        )
        session.refresh(submission)
        assert new_record is not None
        assert new_record.is_system is False
        assert new_record.uploader_id == owner.id
        assert session.get(KnowledgeDocument, old.id) is None
        assert new_version is not None
        assert new_version.version == 4
        assert new_version.source == "user_submission"
        assert new_version.tags == ["心血管", "指南"]
        assert new_version.category == "诊疗规范"
        assert new_version.department == "心内科"
        assert new_version.expires_at.replace(tzinfo=None) == version.expires_at.replace(
            tzinfo=None
        )
        assert new_version.review_due_at.replace(
            tzinfo=None
        ) == version.review_due_at.replace(tzinfo=None)
        assert new_version.last_reviewed_at.replace(
            tzinfo=None
        ) == version.last_reviewed_at.replace(tzinfo=None)
        assert new_version.review_status == "in_review"
        assert submission.document_id == replaced.document_id
        assert submission.status == "published"
        assert submission.original_name == new_record.original_name
        assert submission.stored_name == new_record.stored_name
        assert submission.content_hash == new_record.content_hash
        assert submission.size_bytes == new_record.size_bytes
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "knowledge_asset.file_replaced")
        )
        assert audit is not None
        assert audit.actor_user_id == "admin-user"
        assert audit.request_id == "replace-request"
        assert audit.details["source_type"] == "user_submission"
    finally:
        session.close()
        engine.dispose()


def test_admin_delete_user_asset_archives_and_unlinks_submission(tmp_path) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        owner = User(id="delete-owner", email="delete-owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        record = asyncio.run(
            service.lifecycle.create_document(
                make_upload("待删除用户资料.txt", "管理员永久删除的用户资料"),
                uploader_id=owner.id,
                is_system=False,
            )
        )
        submission = KnowledgeSubmission(
            id="delete-submission",
            submitter_id=owner.id,
            original_name=record.original_name,
            stored_name=record.stored_name,
            content_hash=record.content_hash,
            size_bytes=record.size_bytes,
            status="published",
            parse_warnings=[],
            document_id=record.id,
        )
        session.add(submission)
        session.commit()

        service.audit = SqlAlchemyAuditRecorder(session)
        deleted = service.delete_document(
            record.id,
            actor_user_id="admin-user",
            request_id="delete-request",
        )

        session.refresh(submission)
        assert deleted.document_id == record.id
        assert session.get(KnowledgeDocument, record.id) is None
        assert submission.status == "archived"
        assert submission.document_id is None
        assert session.scalar(
            select(AuditEvent).where(AuditEvent.action == "knowledge_asset.permanently_deleted")
        ) is not None
    finally:
        session.close()
        engine.dispose()


def test_admin_delete_lock_conflict_returns_busy_without_side_effects(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        monkeypatch.setattr(
            service.repository,
            "get_by_id_for_update",
            lambda _document_id: (_ for _ in ()).throw(DocumentLockConflictError()),
        )
        with pytest.raises(DocumentBusyError) as exc_info:
            service.delete_document(
                "busy",
                actor_user_id="admin-user",
                request_id="busy-delete",
            )
        assert exc_info.value.status_code == 409
        assert not vector_store.entries
    finally:
        session.close()
        engine.dispose()


def test_admin_delete_failure_restores_published_submission_and_storage(
    tmp_path, monkeypatch
) -> None:
    service, vector_store, session, engine = build_admin_service(tmp_path)
    try:
        owner = User(id="restore-owner", email="restore-owner@example.com", password_hash="hash")
        session.add(owner)
        session.commit()
        record = asyncio.run(
            service.lifecycle.create_document(
                make_upload("恢复资料.txt", "删除失败后必须完整恢复"),
                uploader_id=owner.id,
                is_system=False,
            )
        )
        submission = KnowledgeSubmission(
            id="restore-submission",
            submitter_id=owner.id,
            original_name=record.original_name,
            stored_name=record.stored_name,
            content_hash=record.content_hash,
            size_bytes=record.size_bytes,
            status="published",
            parse_warnings=[],
            document_id=record.id,
        )
        session.add(submission)
        session.commit()
        old_ids = list(record.chunk_ids)

        def fail_after_partial_delete(ids):
            vector_store.entries.pop(ids[0], None)
            raise RuntimeError("模拟删除向量失败")

        monkeypatch.setattr(vector_store, "delete_documents", fail_after_partial_delete)
        with pytest.raises(DocumentStoreError):
            service.delete_document(
                record.id,
                actor_user_id="admin-user",
                request_id="restore-delete",
            )

        session.expire_all()
        restored = session.get(KnowledgeDocument, record.id)
        restored_submission = session.get(KnowledgeSubmission, submission.id)
        assert restored is not None
        assert restored_submission is not None
        assert restored_submission.status == "published"
        assert restored_submission.document_id == record.id
        assert set(old_ids) <= set(vector_store.entries)
        assert (service.settings.upload_dir / record.stored_name).is_file()
        assert session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "knowledge_asset.permanently_deleted"
            )
        ) is None
    finally:
        session.close()
        engine.dispose()
