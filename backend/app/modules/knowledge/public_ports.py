"""供其他业务模块使用的公共知识只读契约。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PublishedDocumentInfo:
    document_id: str
    file_name: str
    status: str
    source: str | None
    tags: tuple[str, ...]
    version: int
    chunk_count: int
    created_at: datetime
    replaces_document_id: str | None = None
    category: str | None = None
    department: str | None = None
    expires_at: datetime | None = None
    review_due_at: datetime | None = None
    review_status: str = "current"


@dataclass(frozen=True, slots=True)
class PublishedDocumentContent:
    document_id: str
    file_name: str
    text: str
    page_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublishedDocumentFile:
    document_id: str
    file_name: str
    mime_type: str
    content: bytes


class PublishedKnowledgeCatalogPort(Protocol):
    """只暴露可公开检索的知识资产元数据。"""

    def get_published_document(
        self, document_id: str
    ) -> PublishedDocumentInfo | None: ...

    def get_published_content(
        self, document_id: str
    ) -> PublishedDocumentContent | None: ...

    def read_published_file(self, document_id: str) -> PublishedDocumentFile | None: ...
