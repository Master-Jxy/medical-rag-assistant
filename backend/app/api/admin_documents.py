"""管理员知识文档兼容接口；业务判断统一委托知识生命周期。"""

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.schemas.document import DocumentDeleteResponse, DocumentUploadResponse
from app.services.admin_document_service import (
    AdminDocumentService,
    get_admin_document_service,
)

router = APIRouter(prefix="/admin/documents", tags=["管理员知识资产"])


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def create_system_document(
    request: Request,
    file: UploadFile = File(description="不超过 10 MB 的 PDF、TXT、DOCX、Markdown 或 HTML 文件"),
    admin: UserResponse = Depends(require_admin),
    service: AdminDocumentService = Depends(get_admin_document_service),
) -> DocumentUploadResponse:
    return await service.create_system_document(
        file,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: str,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: AdminDocumentService = Depends(get_admin_document_service),
) -> DocumentDeleteResponse:
    return service.delete_document(
        document_id,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.put("/{document_id}/replace", response_model=DocumentUploadResponse)
async def replace_document(
    document_id: str,
    request: Request,
    file: UploadFile = File(description="用于整体替换的 PDF、TXT、DOCX、Markdown 或 HTML 文件"),
    admin: UserResponse = Depends(require_admin),
    service: AdminDocumentService = Depends(get_admin_document_service),
) -> DocumentUploadResponse:
    return await service.replace_document(
        document_id,
        file,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )
