"""管理员系统文档接口；所有端点统一依赖数据库角色授权。"""

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.schemas.document import DocumentDeleteResponse, DocumentUploadResponse
from app.services.admin_document_service import (
    AdminDocumentService,
    get_admin_document_service,
)

router = APIRouter(prefix="/admin/documents", tags=["管理员知识库"])


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def create_system_document(
    file: UploadFile = File(description="不超过 10 MB 的 PDF 或 UTF-8 TXT 文件"),
    admin: UserResponse = Depends(require_admin),
    service: AdminDocumentService = Depends(get_admin_document_service),
) -> DocumentUploadResponse:
    return await service.create_system_document(file, actor_user_id=admin.id)


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_system_document(
    document_id: str,
    _admin: UserResponse = Depends(require_admin),
    service: AdminDocumentService = Depends(get_admin_document_service),
) -> DocumentDeleteResponse:
    return service.delete_system_document(document_id)


@router.put("/{document_id}/replace", response_model=DocumentUploadResponse)
async def replace_system_document(
    document_id: str,
    file: UploadFile = File(description="用于整体替换的 PDF 或 UTF-8 TXT 文件"),
    admin: UserResponse = Depends(require_admin),
    service: AdminDocumentService = Depends(get_admin_document_service),
) -> DocumentUploadResponse:
    return await service.replace_system_document(
        document_id, file, actor_user_id=admin.id
    )
