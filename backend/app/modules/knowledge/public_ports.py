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


@dataclass(frozen=True, slots=True)
class PublishedDocumentContent:
    document_id: str
    file_name: str
    text: str
    page_count: int
    warnings: tuple[str, ...]


class PublishedKnowledgeCatalogPort(Protocol):
    """只暴露可公开检索的知识资产元数据。"""

    def get_published_document(
        self, document_id: str
    ) -> PublishedDocumentInfo | None: ...

    def get_published_content(
        self, document_id: str
    ) -> PublishedDocumentContent | None: ...
