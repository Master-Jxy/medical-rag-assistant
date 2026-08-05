"""管理员资料审核接口。"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.knowledge_parser_factory import create_knowledge_document_parser
from app.infrastructure.vector_store import VectorStoreService
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.modules.jobs.service import SqlAlchemyJobService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.review_schemas import (
    ApprovalResponse,
    RejectSubmissionRequest,
    ReviewItem,
    ReviewListResponse,
)
from app.modules.knowledge.metadata_suggestions import (
    MetadataSuggestionDecisionRequest,
    MetadataSuggestionItem,
    MetadataSuggestionRejectRequest,
    MetadataSuggestionService,
    create_metadata_suggestion_port,
)
from app.modules.knowledge.review_service import KnowledgeReviewService
from app.services.document_service import get_vector_store_service

router = APIRouter(prefix="/admin/reviews", tags=["管理员资料审核"])


def get_review_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreService = Depends(get_vector_store_service),
) -> KnowledgeReviewService:
    return KnowledgeReviewService(
        session,
        settings,
        DocumentLifecycleService(
            session,
            settings,
            vector_store,
            parser=create_knowledge_document_parser(settings),
        ),
        SqlAlchemyAuditRecorder(session),
        SqlAlchemyJobService(session),
        metadata_suggestions=MetadataSuggestionService(
            session,
            SqlAlchemyAuditRecorder(session),
            create_metadata_suggestion_port(settings.metadata_suggestion_mode),
        ),
    )


@router.get("", response_model=ReviewListResponse)
def list_reviews(
    status: str | None = Query(default="pending_review", max_length=30),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> ReviewListResponse:
    return service.list_reviews(status=status, offset=offset, limit=limit)


@router.get("/{submission_id}", response_model=ReviewItem)
def get_review(
    submission_id: str,
    _admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> ReviewItem:
    return service.get_review(submission_id)


@router.post("/{submission_id}/metadata-suggestion/generate", response_model=MetadataSuggestionItem)
def generate_metadata_suggestion(
    submission_id: str,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> MetadataSuggestionItem:
    return service.metadata_suggestions.generate(
        submission_id,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{submission_id}/metadata-suggestion/accept", response_model=MetadataSuggestionItem)
def accept_metadata_suggestion(
    submission_id: str,
    payload: MetadataSuggestionDecisionRequest,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> MetadataSuggestionItem:
    return service.metadata_suggestions.accept(
        submission_id,
        payload,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{submission_id}/metadata-suggestion/reject", response_model=MetadataSuggestionItem)
def reject_metadata_suggestion(
    submission_id: str,
    payload: MetadataSuggestionRejectRequest,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> MetadataSuggestionItem:
    return service.metadata_suggestions.reject(
        submission_id,
        payload,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{submission_id}/reject", response_model=ApprovalResponse)
def reject_review(
    submission_id: str,
    payload: RejectSubmissionRequest,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> ApprovalResponse:
    return service.reject(
        submission_id,
        payload.reason,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/{submission_id}/approve", response_model=ApprovalResponse)
async def approve_review(
    submission_id: str,
    request: Request,
    admin: UserResponse = Depends(require_admin),
    service: KnowledgeReviewService = Depends(get_review_service),
) -> ApprovalResponse:
    return await service.approve(
        submission_id,
        actor_user_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
    )
