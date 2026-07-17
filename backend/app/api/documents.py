"""知识库文档管理接口。"""

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.schemas.document import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService, get_document_service

router = APIRouter(tags=["知识库管理"])


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="上传并向量化 PDF/TXT 文档",
)
async def upload_document(
    file: UploadFile = File(description="不超过 10 MB 的 PDF 或 UTF-8 TXT 文件"),
    current_user: UserResponse = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentUploadResponse:
    """路由只接收文件，完整入库过程交给 DocumentService。"""
    return await document_service.process_upload(current_user.id, file)


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="获取已上传文档列表",
)
def list_documents(
    current_user: UserResponse = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    """返回登记表中的文档，不读取或返回完整文档正文。"""
    return document_service.list_documents(current_user.id)


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="删除文档及其全部向量片段",
)
def delete_document(
    document_id: str,
    current_user: UserResponse = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service),
) -> DocumentDeleteResponse:
    """把删除工作交给服务层，路由不直接操作文件或 Chroma。"""
    return document_service.delete_document(current_user.id, document_id)
