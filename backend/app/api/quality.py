"""用户回答反馈与管理员质量复核接口。"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user, require_admin
from app.modules.auth.schemas import UserResponse
from app.modules.quality.repository import QualityRepository
from app.modules.quality.schemas import (
    FeedbackResponse,
    FeedbackReviewUpdate,
    FeedbackUpsert,
    QualityOverview,
    ReviewDetail,
    ReviewQueueResponse,
)
from app.modules.quality.service import QualityService
from app.services.conversation_quality_query import ConversationQualityQueryService

router = APIRouter(tags=["回答质量"])


def get_quality_service(session: Session = Depends(get_db_session)) -> QualityService:
    return QualityService(
        QualityRepository(session),
        ConversationQualityQueryService(session),
    )


@router.put("/quality/messages/{message_id}/feedback", response_model=FeedbackResponse)
def upsert_feedback(
    message_id: str,
    payload: FeedbackUpsert,
    current_user: UserResponse = Depends(get_current_user),
    service: QualityService = Depends(get_quality_service),
):
    return service.upsert(current_user.id, message_id, payload)


@router.delete(
    "/quality/messages/{message_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_feedback(
    message_id: str,
    current_user: UserResponse = Depends(get_current_user),
    service: QualityService = Depends(get_quality_service),
):
    service.delete(current_user.id, message_id)
    return Response(status_code=204)


@router.get("/admin/quality/overview", response_model=QualityOverview)
def quality_overview(
    _: UserResponse = Depends(require_admin),
    service: QualityService = Depends(get_quality_service),
):
    return service.overview()


@router.get("/admin/quality/reviews", response_model=ReviewQueueResponse)
def quality_queue(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _: UserResponse = Depends(require_admin),
    service: QualityService = Depends(get_quality_service),
):
    return service.queue(offset, limit)


@router.get("/admin/quality/reviews/{feedback_id}", response_model=ReviewDetail)
def quality_detail(
    feedback_id: str,
    _: UserResponse = Depends(require_admin),
    service: QualityService = Depends(get_quality_service),
):
    return service.detail(feedback_id)


@router.patch("/admin/quality/reviews/{feedback_id}", response_model=FeedbackResponse)
def review_feedback(
    feedback_id: str,
    payload: FeedbackReviewUpdate,
    current_user: UserResponse = Depends(require_admin),
    service: QualityService = Depends(get_quality_service),
):
    return service.review(feedback_id, current_user.id, payload)
