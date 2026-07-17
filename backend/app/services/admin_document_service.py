"""管理员系统文档用例；授权由路由依赖负责，存储一致性由共享生命周期负责。"""

from fastapi import Depends, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentStoreError,
    SystemDocumentRequiredError,
)
from app.db.session import get_db_session
from app.infrastructure.vector_store import VectorStoreService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.repository import DocumentRepository
from app.schemas.document import DocumentDeleteResponse, DocumentUploadResponse
from app.services.document_service import document_to_item, get_vector_store_service
from app.services.upload_protection_service import (
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
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.vector_store = vector_store or VectorStoreService(self.settings)
        self.upload_protection = upload_protection
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
    ) -> DocumentUploadResponse:
        async def create_document():
            return await self.lifecycle.create_document(
                upload_file, uploader_id=None, is_system=True
            )

        try:
            record = (
                await self.upload_protection.execute(actor_user_id, create_document)
                if self.upload_protection is not None and actor_user_id is not None
                else await create_document()
            )
        finally:
            await upload_file.close()
        return DocumentUploadResponse(
            **document_to_item(record, can_delete=True).model_dump()
        )

    def delete_system_document(self, document_id: str) -> DocumentDeleteResponse:
        try:
            record = self.repository.get_by_id(document_id)
        except SQLAlchemyError as exc:
            raise DocumentStoreError() from exc
        if record is None:
            raise DocumentNotFoundError()
        if not record.is_system:
            raise SystemDocumentRequiredError()
        deleted_id = self.lifecycle.delete_document(record)
        return DocumentDeleteResponse(document_id=deleted_id)

    async def replace_system_document(
        self,
        document_id: str,
        upload_file: UploadFile,
        *,
        actor_user_id: str | None = None,
    ) -> DocumentUploadResponse:
        async def replace_document():
            return await self.lifecycle.replace_system_document(document_id, upload_file)

        try:
            record = (
                await self.upload_protection.execute(actor_user_id, replace_document)
                if self.upload_protection is not None and actor_user_id is not None
                else await replace_document()
            )
        finally:
            await upload_file.close()
        return DocumentUploadResponse(
            **document_to_item(record, can_delete=True).model_dump()
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
