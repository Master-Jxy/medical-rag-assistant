"""已发布文档预览与版本来源追溯。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.exceptions import DocumentNotFoundError
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.modules.knowledge.public_catalog import PublishedKnowledgeCatalogService

router = APIRouter(prefix="/knowledge/documents", tags=["公共知识追溯"])


class DocumentTraceResponse(BaseModel):
    document_id: str
    file_name: str
    source: str | None
    tags: list[str]
    version: int
    replaces_document_id: str | None
    created_at: str
    category: str | None
    department: str | None
    expires_at: str | None
    review_due_at: str | None
    review_status: str


@router.get("/{document_id}/trace", response_model=DocumentTraceResponse)
def trace_document(
    document_id: str,
    _: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    item = PublishedKnowledgeCatalogService(
        session, settings=settings
    ).get_published_document(document_id)
    if item is None:
        raise DocumentNotFoundError()
    return DocumentTraceResponse(
        document_id=item.document_id, file_name=item.file_name, source=item.source,
        tags=list(item.tags), version=item.version, replaces_document_id=item.replaces_document_id,
        created_at=item.created_at.isoformat(),
        category=item.category,
        department=item.department,
        expires_at=item.expires_at.isoformat() if item.expires_at else None,
        review_due_at=item.review_due_at.isoformat() if item.review_due_at else None,
        review_status=item.review_status,
    )


@router.get("/{document_id}/preview")
def preview_document(
    document_id: str,
    _: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    item = PublishedKnowledgeCatalogService(
        session, settings=settings
    ).read_published_file(document_id)
    if item is None:
        raise DocumentNotFoundError()
    return Response(
        content=item.content,
        media_type=item.mime_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(item.file_name)}"},
    )
