"""管理员知识文档用例；授权由路由依赖负责，存储一致性由共享生命周期负责。"""

from fastapi import Depends, UploadFile
from sqlalchemy.orm import Session
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.vector_store import VectorStoreService
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.models import DocumentVersion
from app.modules.knowledge.repository import DocumentRepository
from app.schemas.document import DocumentDeleteResponse, DocumentUploadResponse
from app.services.document_service import document_to_item, get_vector_store_service
from app.services.upload_protection_service import (
    ADMIN_UPLOAD_POLICY,
    UploadProtectionService,
    get_upload_protection_service,
)


class AdminDocumentService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        vector_store: VectorStoreService | None = None,
        upload_protection: UploadProtectionService | None = None,
        audit: AuditPort | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStoreService(self.settings)
        self.upload_protection = upload_protection
        self.audit = audit or SqlAlchemyAuditRecorder(session)
        self.repository = DocumentRepository(session)
        self.lifecycle = DocumentLifecycleService(
            session,
            self.settings,
            self.vector_store,
            repository=self.repository,
        )

    async def create_system_document(
        self,
        upload_file: UploadFile,
        *,
        actor_user_id: str | None = None,
        request_id: str | None = None,
    ) -> DocumentUploadResponse:
        async def create_document():
            return await self.lifecycle.create_document(
                upload_file, uploader_id=None, is_system=True
            )

        try:
            record = (
                await self.upload_protection.execute(
                    actor_user_id,
                    create_document,
                    policy=ADMIN_UPLOAD_POLICY,
                )
                if self.upload_protection is not None and actor_user_id is not None
                else await create_document()
            )
        finally:
            await upload_file.close()
        self.session.add(
            DocumentVersion(
                id=str(uuid4()),
                document_id=record.id,
                version=1,
                source="system",
                tags=[],
            )
        )
        if actor_user_id is not None:
            self.audit.record(
                AuditRecord(
                    actor_user_id=actor_user_id,
                    action="knowledge_asset.created",
                    object_type="knowledge_document",
                    object_id=record.id,
                    request_id=request_id,
                    details={"source_type": "system"},
                )
            )
        self.session.commit()
        return DocumentUploadResponse(
            **document_to_item(record, can_delete=True).model_dump()
        )

    def delete_document(
        self,
        document_id: str,
        *,
        actor_user_id: str | None = None,
        request_id: str | None = None,
    ) -> DocumentDeleteResponse:
        deleted_id = self.lifecycle.delete_managed_document(
            document_id,
            audit=self.audit,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        return DocumentDeleteResponse(document_id=deleted_id)

    def delete_system_document(
        self,
        document_id: str,
        *,
        actor_user_id: str | None = None,
        request_id: str | None = None,
    ) -> DocumentDeleteResponse:
        """兼容旧调用；系统资料与用户发布资料共用治理生命周期。"""
        return self.delete_document(
            document_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    async def replace_document(
        self,
        document_id: str,
        upload_file: UploadFile,
        *,
        actor_user_id: str | None = None,
        request_id: str | None = None,
    ) -> DocumentUploadResponse:
        async def perform_replace():
            return await self.lifecycle.replace_document(
                document_id,
                upload_file,
                audit=self.audit,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )

        try:
            record = (
                await self.upload_protection.execute(
                    actor_user_id,
                    perform_replace,
                    policy=ADMIN_UPLOAD_POLICY,
                )
                if self.upload_protection is not None and actor_user_id is not None
                else await perform_replace()
            )
        finally:
            await upload_file.close()
        return DocumentUploadResponse(
            **document_to_item(record, can_delete=True).model_dump()
        )

    async def replace_system_document(
        self,
        document_id: str,
        upload_file: UploadFile,
        *,
        actor_user_id: str | None = None,
        request_id: str | None = None,
    ) -> DocumentUploadResponse:
        """兼容旧调用；系统资料与用户发布资料共用治理生命周期。"""
        return await self.replace_document(
            document_id,
            upload_file,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )


def get_admin_document_service(
    session: Session = Depends(get_db_session),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
    upload_protection: UploadProtectionService = Depends(
        get_upload_protection_service
    ),
) -> AdminDocumentService:
    return AdminDocumentService(
        session=session,
        vector_store=vector_store,
        upload_protection=upload_protection,
    )
