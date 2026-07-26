"""反馈提交、复核与质量聚合应用服务。"""

from app.core.exceptions import AppError
from app.modules.quality.models import AnswerFeedback
from app.modules.quality.ports import ConversationQualityPort
from app.modules.quality.repository import QualityRepository
from app.modules.quality.schemas import (
    FeedbackResponse,
    FeedbackReviewUpdate,
    FeedbackUpsert,
    QualityOverview,
    ReviewDetail,
    ReviewQueueItem,
    ReviewQueueResponse,
)


class FeedbackNotFoundError(AppError):
    def __init__(self):
        super().__init__("未找到可操作的回答反馈", code="FEEDBACK_NOT_FOUND", status_code=404)


class QualityService:
    def __init__(self, repository: QualityRepository, conversations: ConversationQualityPort):
        self.repository = repository
        self.conversations = conversations
        self.session = repository.session

    def upsert(self, user_id: str, message_id: str, payload: FeedbackUpsert):
        if not self.conversations.user_owns_completed_answer(user_id, message_id):
            raise FeedbackNotFoundError()
        feedback = self.repository.get_by_message(message_id)
        if feedback is not None and feedback.user_id != user_id:
            raise FeedbackNotFoundError()
        if feedback is None:
            feedback = AnswerFeedback(message_id=message_id, user_id=user_id)
            self.session.add(feedback)
        feedback.rating = payload.rating
        feedback.question_category = payload.question_category
        feedback.issue_category = payload.issue_category
        feedback.comment = payload.comment
        feedback.review_status = "pending" if payload.rating == "down" else "resolved"
        feedback.reviewer_id = None
        feedback.review_note = None
        feedback.reviewed_at = None
        self.session.commit()
        self.session.refresh(feedback)
        return FeedbackResponse.model_validate(feedback)

    def delete(self, user_id: str, message_id: str) -> None:
        feedback = self.repository.get_owned(user_id, message_id)
        if feedback is None:
            raise FeedbackNotFoundError()
        self.session.delete(feedback)
        self.session.commit()

    def overview(self) -> QualityOverview:
        data = self.repository.overview()
        total = data["total"]
        return QualityOverview(
            **data,
            positive_rate=(data["positive"] / total if total else None),
        )

    def queue(self, offset: int, limit: int) -> ReviewQueueResponse:
        items, total = self.repository.list_pending(offset, limit)
        return ReviewQueueResponse(
            items=[ReviewQueueItem.model_validate(item) for item in items],
            total=total,
            offset=offset,
            limit=limit,
        )

    def detail(self, feedback_id: str) -> ReviewDetail:
        feedback = self.repository.get(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError()
        context = self.conversations.get_review_context(feedback.message_id)
        if context is None:
            raise FeedbackNotFoundError()
        return ReviewDetail(
            feedback=ReviewQueueItem.model_validate(feedback),
            conversation_id=context.conversation_id,
            question_excerpt=context.question_excerpt,
            answer_excerpt=context.answer_excerpt,
            source_names=list(context.source_names),
        )

    def review(self, feedback_id: str, reviewer_id: str, payload: FeedbackReviewUpdate):
        feedback = self.repository.get(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError()
        self.repository.mark_reviewed(
            feedback,
            status=payload.status,
            reviewer_id=reviewer_id,
            note=payload.note.strip(),
        )
        self.session.commit()
        return FeedbackResponse.model_validate(feedback)
