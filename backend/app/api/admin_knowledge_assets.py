"""管理员知识资产接口。"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.vector_store import VectorStoreService
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.modules.knowledge.asset_schemas import (
    AssetMetadataUpdate,
    KnowledgeAssetItem,
    KnowledgeAssetListResponse,
    ReplacementRequest,
)
from app.modules.knowledge.asset_service import KnowledgeAssetService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.services.document_service import get_vector_store_service

router = APIRouter(prefix="/admin/knowledge-assets", tags=["管理员知识资产"])


def get_asset_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> KnowledgeAssetService:
    return KnowledgeAssetService(
        session,
        DocumentLifecycleService(session, settings, vector_store),
        SqlAlchemyAuditRecorder(session),
    )


@router.get("", response_model=KnowledgeAssetListResponse)
def list_assets(
    status: str | None = Query(default=None, max_length=20),
    source: str | None = Query(default=None, max_length=255),
    tag: str | None = Query(default=None, max_length=50),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: UserResponse = Depends(require_admin),
    service: KnowledgeAssetService = Depends(get_asset_service),
) -> KnowledgeAssetListResponse:
    return service.list_assets(
        status=status,
        source=source,
        tag=tag,
        offset=offset,
        limit=limit,
    )


@router.patch("/{document_id}", response_model=KnowledgeAssetItem)
def update_asset(
    document_id: str,
    payload: AssetMetadataUpdate,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeAssetService = Depends(get_asset_service),
) -> KnowledgeAssetItem:
    return service.update_metadata(
        document_id,
        source=payload.source,
        tags=payload.tags,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{document_id}/archive", response_model=KnowledgeAssetItem)
def archive_asset(
    document_id: str,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeAssetService = Depends(get_asset_service),
) -> KnowledgeAssetItem:
    return service.archive(
        document_id,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{document_id}/republish", response_model=KnowledgeAssetItem)
def republish_asset(
    document_id: str,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeAssetService = Depends(get_asset_service),
) -> KnowledgeAssetItem:
    return service.republish(
        document_id,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{document_id}/replace", response_model=KnowledgeAssetItem)
def replace_asset(
    document_id: str,
    payload: ReplacementRequest,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeAssetService = Depends(get_asset_service),
) -> KnowledgeAssetItem:
    return service.replace(
        document_id,
        payload.replacement_document_id,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )
