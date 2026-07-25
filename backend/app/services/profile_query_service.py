"""跨会话与知识模块聚合当前用户的个人中心只读数据。"""

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message
from app.modules.auth.schemas import UserResponse
from app.modules.knowledge.submission_queries import MySubmissionQueryService


class PersonalStatsResponse(BaseModel):
    conversation_count: int
    message_count: int
    submitted_document_count: int


class ProfileQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.submissions = MySubmissionQueryService(session)

    def get_profile(self, current_user: UserResponse) -> UserResponse:
        return current_user

    def get_stats(self, user_id: str) -> PersonalStatsResponse:
        conversation_count = self.session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == user_id)
        ) or 0
        message_count = self.session.scalar(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id == user_id)
        ) or 0
        return PersonalStatsResponse(
            conversation_count=conversation_count,
            message_count=message_count,
            submitted_document_count=self.submissions.count_for_user(user_id),
        )
