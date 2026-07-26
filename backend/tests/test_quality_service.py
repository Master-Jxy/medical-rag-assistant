"""任务12.1：回答反馈、用户隔离、复核与质量聚合。"""

from sqlalchemy.orm import Session
import pytest

from app.db.base import Base
from app.db.session import build_engine
from app.models import Conversation, Message, User
from app.modules.quality.repository import QualityRepository
from app.modules.quality.schemas import FeedbackReviewUpdate, FeedbackUpsert
from app.modules.quality.service import FeedbackNotFoundError, QualityService
from app.services.conversation_quality_query import ConversationQualityQueryService


def setup_data(session):
    session.add_all(
        [
            User(id="owner", email="owner@example.com", password_hash="hash"),
            User(id="other", email="other@example.com", password_hash="hash"),
            User(id="admin", email="admin@example.com", password_hash="hash", role="admin"),
        ]
    )
    conversation = Conversation(id="conversation-1", user_id="owner", title="测试")
    conversation.messages = [
        Message(id="question-1", sequence=1, role="user", content="问题"),
        Message(id="answer-1", sequence=2, role="assistant", content="回答"),
    ]
    session.add(conversation)
    session.commit()


def test_feedback_is_owned_upserted_and_reviewed_without_copying_answer() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        setup_data(session)
        service = QualityService(
            QualityRepository(session),
            ConversationQualityQueryService(session),
        )
        feedback = service.upsert(
            "owner",
            "answer-1",
            FeedbackUpsert(
                rating="down",
                question_category="general",
                issue_category="incomplete",
                comment="缺少关键说明",
            ),
        )
        assert feedback.review_status == "pending"
        with pytest.raises(FeedbackNotFoundError):
            service.upsert(
                "other",
                "answer-1",
                FeedbackUpsert(rating="up", question_category="general"),
            )
        overview = service.overview()
        assert overview.total == 1
        assert overview.negative == 1
        assert overview.issue_counts == {"incomplete": 1}
        assert overview.daily_counts[0].negative == 1
        assert service.queue(0, 20).total == 1
        detail = service.detail(feedback.id)
        assert detail.question_excerpt == "问题"
        assert detail.answer_excerpt == "回答"
        reviewed = service.review(
            feedback.id,
            "admin",
            FeedbackReviewUpdate(status="resolved", note="已复核"),
        )
        assert reviewed.review_status == "resolved"
        assert service.overview().pending_review == 0
    engine.dispose()


def test_upvote_closes_queue_and_user_can_delete_own_feedback() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        setup_data(session)
        service = QualityService(
            QualityRepository(session),
            ConversationQualityQueryService(session),
        )
        feedback = service.upsert(
            "owner",
            "answer-1",
            FeedbackUpsert(rating="up", question_category="prevention"),
        )
        assert feedback.review_status == "resolved"
        assert service.overview().positive_rate == 1
        service.delete("owner", "answer-1")
        assert service.overview().total == 0
    engine.dispose()
