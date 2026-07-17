"""普通用户的公共文档用例；底层一致性由共享生命周期负责。"""

from functools import lru_cache

from fastapi import Depends, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    DocumentDeleteForbiddenError,
    DocumentNotFoundError,
    DocumentStoreError,
)
from app.db.session import get_db_session
from app.infrastructure.vector_store import VectorStoreService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.models import KnowledgeDocument
from app.modules.knowledge.repository import DocumentRepository
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.upload_protection_service import (
    UploadProtectionService,
    get_upload_protection_service,
)


def document_to_item(
    record: KnowledgeDocument, *, can_delete: bool
) -> DocumentItem:
    return DocumentItem(
        document_id=record.id,
        file_name=record.original_name,
        file_size=record.size_bytes,
        chunk_count=record.chunk_count,
        status=record.status,
        is_system=record.is_system,
        can_delete=can_delete,
        created_at=record.created_at,
    )


class DocumentService:
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

    async def process_upload(
        self, user_id: str, upload_file: UploadFile
    ) -> DocumentUploadResponse:
        async def create_document() -> KnowledgeDocument:
            return await self.lifecycle.create_document(
                upload_file, uploader_id=user_id, is_system=False
            )

        try:
            record = (
                await self.upload_protection.execute(user_id, create_document)
                if self.upload_protection is not None
                else await create_document()
            )
        finally:
            # 限流或并发拒绝发生在生命周期启动前，也必须及时关闭上传句柄。
            await upload_file.close()
        return DocumentUploadResponse(
            **document_to_item(record, can_delete=True).model_dump()
        )

    def list_documents(self, user_id: str) -> DocumentListResponse:
        try:
            records = self.repository.list_all()
        except SQLAlchemyError as exc:
            raise DocumentStoreError() from exc
        documents = [
            document_to_item(
                record,
                can_delete=not record.is_system and record.uploader_id == user_id,
            )
            for record in records
        ]
        return DocumentListResponse(documents=documents, total=len(documents))

    def delete_document(self, user_id: str, document_id: str) -> DocumentDeleteResponse:
        try:
            record = self.repository.get_by_id(document_id)
        except SQLAlchemyError as exc:
            raise DocumentStoreError() from exc
        if record is None:
            raise DocumentNotFoundError()
        if record.is_system or record.uploader_id != user_id:
            raise DocumentDeleteForbiddenError()
        deleted_id = self.lifecycle.delete_document(record)
        return DocumentDeleteResponse(document_id=deleted_id)

    def _load_documents(self, *args, **kwargs):
        """保留解析测试入口；实际实现只存在于共享生命周期。"""
        return self.lifecycle._load_documents(*args, **kwargs)


@lru_cache
def get_vector_store_service() -> VectorStoreService:
    return VectorStoreService()


def get_document_service(
    session: Session = Depends(get_db_session),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
    upload_protection: UploadProtectionService = Depends(
        get_upload_protection_service
    ),
) -> DocumentService:
    return DocumentService(
        session=session,
        vector_store=vector_store,
        upload_protection=upload_protection,
    )
