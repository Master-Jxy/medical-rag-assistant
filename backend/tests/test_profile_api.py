"""个人中心只返回当前用户自己的统计和资料。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation, KnowledgeDocument, KnowledgeSubmission, Message
from app.modules.auth.tokens import get_token_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def test_profile_stats_and_my_submissions_are_user_isolated(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'profile.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user = create_test_user(factory, "profile-owner")
    other = create_test_user(factory, "profile-other")
    with factory() as session:
        own_conversation = Conversation(user_id=user.id, title="自己的会话")
        own_conversation.messages = [
            Message(sequence=1, role="user", content="问题"),
            Message(sequence=2, role="assistant", content="回答"),
        ]
        session.add_all(
            [
                own_conversation,
                Conversation(user_id=other.id, title="他人的会话"),
                KnowledgeDocument(
                    id="own-document",
                    original_name="自己的资料.txt",
                    stored_name="own.txt",
                    content_hash="1" * 64,
                    size_bytes=10,
                    chunk_count=1,
                    chunk_ids=["own-document:0"],
                    uploader_id=user.id,
                    is_system=False,
                    status="ready",
                ),
                KnowledgeSubmission(
                    id="own-submission",
                    submitter_id=user.id,
                    original_name="自己的资料.txt",
                    stored_name="own.txt",
                    content_hash="3" * 64,
                    size_bytes=10,
                    status="published",
                    parse_warnings=[],
                    document_id="own-document",
                ),
                KnowledgeSubmission(
                    id="own-pending-submission",
                    submitter_id=user.id,
                    original_name="待审核资料.txt",
                    stored_name="pending.txt",
                    content_hash="4" * 64,
                    size_bytes=10,
                    status="pending_review",
                    parse_warnings=[],
                ),
                KnowledgeDocument(
                    id="other-document",
                    original_name="他人的资料.txt",
                    stored_name="other.txt",
                    content_hash="2" * 64,
                    size_bytes=10,
                    chunk_count=1,
                    chunk_ids=["other-document:0"],
                    uploader_id=other.id,
                    is_system=False,
                    status="ready",
                ),
            ]
        )
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/profile").status_code == 401
            profile = client.get(
                "/api/v1/profile", headers=auth_headers(user.id)
            )
            assert profile.status_code == 200
            assert profile.json()["id"] == user.id

            stats = client.get(
                "/api/v1/me/stats", headers=auth_headers(user.id)
            )
            assert stats.json() == {
                "conversation_count": 1,
                "message_count": 2,
                "submitted_document_count": 2,
            }

            submissions = client.get(
                "/api/v1/knowledge/submissions",
                headers=auth_headers(user.id),
            )
            assert submissions.status_code == 200
            assert submissions.json()["total"] == 2
            item = submissions.json()["items"][0]
            assert {
                entry["submission_id"] for entry in submissions.json()["items"]
            } == {"own-submission", "own-pending-submission"}
            assert "他人的" not in str(submissions.json())
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
