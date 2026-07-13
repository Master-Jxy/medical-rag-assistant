"""文档上传接口的响应结构。"""

from datetime import datetime

from pydantic import BaseModel


class DocumentItem(BaseModel):
    """对外展示的文档基本信息，不暴露服务器保存路径和哈希。"""

    document_id: str
    file_name: str
    file_size: int
    chunk_count: int
    status: str = "ready"
    created_at: datetime


class DocumentUploadResponse(DocumentItem):
    """文档成功保存并写入 Chroma 后返回的信息。"""


class DocumentListResponse(BaseModel):
    """知识库文档列表。"""

    documents: list[DocumentItem]
    total: int


class DocumentDeleteResponse(BaseModel):
    """文档及其向量成功删除后的响应。"""

    document_id: str
    message: str = "文档已删除"
