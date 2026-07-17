"""多轮上下文测试：验证最近轮数、状态过滤、字符预算和检索补全。"""

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import Conversation, Message, User
from app.services.conversation_chat_service import ConversationChatService
from app.services.rag_service import RagService
from app.services.generation_lock_service import GenerationLockLease
from tests.idempotency_helpers import AllowingIdempotency


class CapturingRagService:
    def __init__(self) -> None:
        self.histories = []

    def ask(self, question: str, top_k: int, history=None):
        self.histories.append(list(history or []))
        return f"回答：{question}", []


class AllowingGenerationLock:
    def acquire(self, user_id: str, conversation_id: str) -> GenerationLockLease:
        return GenerationLockLease("history-lock", "history-owner")

    def release(self, lease: GenerationLockLease) -> None:
        pass


def test_only_latest_three_rounds_are_passed_in_chronological_order() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    rag = CapturingRagService()
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                id="history-rounds-user",
                email="history-rounds@example.com",
                password_hash="not-used",
            )
            conversation = Conversation(user_id=user.id, title="多轮测试")
            session.add_all([user, conversation])
            session.commit()
            service = ConversationChatService(
                session, rag, AllowingGenerationLock(), AllowingIdempotency()
            )

            for index in range(1, 6):
                service.ask(
                    user.id, conversation.id, f"问题{index}", 2, f"history-{index}"
                )

            assert rag.histories[0] == []
            assert rag.histories[1] == [("user", "问题1"), ("assistant", "回答：问题1")]
            assert rag.histories[4] == [
                ("user", "问题2"),
                ("assistant", "回答：问题2"),
                ("user", "问题3"),
                ("assistant", "回答：问题3"),
                ("user", "问题4"),
                ("assistant", "回答：问题4"),
            ]
    finally:
        engine.dispose()


def test_history_excludes_failed_pending_and_applies_character_budget() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            user = User(
                id="history-filter-user",
                email="history-filter@example.com",
                password_hash="not-used",
            )
            conversation = Conversation(user_id=user.id, title="过滤测试")
            conversation.messages.extend(
                [
                    Message(sequence=1, role="user", content="旧内容", status="completed"),
                    Message(sequence=2, role="assistant", content="旧回答", status="completed"),
                    Message(sequence=3, role="user", content="abcde", status="completed"),
                    Message(sequence=4, role="assistant", content="失败", status="failed"),
                    Message(sequence=5, role="assistant", content="等待", status="pending"),
                    Message(sequence=6, role="assistant", content="stop", status="stopped"),
                ]
            )
            session.add_all([user, conversation])
            session.commit()

            service = ConversationChatService(
                session,
                CapturingRagService(),
                AllowingGenerationLock(),
                AllowingIdempotency(),
            )
            service.max_history_messages = 6
            service.max_history_chars = 9
            history = service._load_recent_history(user.id, conversation.id)

            assert history == [("user", "abcde"), ("assistant", "stop")]
            assert all(content not in {"失败", "等待"} for _, content in history)
    finally:
        engine.dispose()


def test_retrieval_query_uses_last_user_question_for_pronoun_followup() -> None:
    history = [
        ("user", "高血压有哪些常见症状？"),
        ("assistant", "部分患者可能没有明显症状。"),
    ]

    query = RagService._build_retrieval_query("那它一般怎么管理？", history)

    assert "高血压有哪些常见症状" in query
    assert "那它一般怎么管理" in query
