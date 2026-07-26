"""公共知识目录的只读应用服务。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.knowledge.models import DocumentVersion, KnowledgeDocument
from app.modules.knowledge.parser import LocalDocumentParser, ParserPort
from app.modules.knowledge.public_ports import (
    PublishedDocumentContent,
    PublishedDocumentInfo,
)

PUBLIC_DOCUMENT_STATUSES = ("published", "ready")


class PublishedKnowledgeCatalogService:
    """将数据库模型收敛成跨模块可用的只读契约。"""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        parser: ParserPort | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.parser = parser or LocalDocumentParser()

    def get_published_document(
        self, document_id: str
    ) -> PublishedDocumentInfo | None:
        row = self.session.execute(
            select(KnowledgeDocument, DocumentVersion)
            .outerjoin(
                DocumentVersion,
                DocumentVersion.document_id == KnowledgeDocument.id,
            )
            .where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.status.in_(PUBLIC_DOCUMENT_STATUSES),
            )
        ).one_or_none()
        if row is None:
            return None
        document, version = row
        return PublishedDocumentInfo(
            document_id=document.id,
            file_name=document.original_name,
            status=document.status,
            source=version.source if version else None,
            tags=tuple(version.tags or ()) if version else (),
            version=version.version if version else 1,
            chunk_count=document.chunk_count,
            created_at=document.created_at,
        )

    def get_published_content(
        self, document_id: str
    ) -> PublishedDocumentContent | None:
        document = self.session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.status.in_(PUBLIC_DOCUMENT_STATUSES),
            )
        )
        if document is None:
            return None
        upload_root = self.settings.upload_dir.resolve()
        path = (upload_root / document.stored_name).resolve()
        if upload_root not in path.parents or not path.is_file():
            return None
        preview = self.parser.parse(path, path.suffix.lower())
        return PublishedDocumentContent(
            document_id=document.id,
            file_name=document.original_name,
            text=preview.text,
            page_count=preview.page_count,
            warnings=preview.warnings,
        )
