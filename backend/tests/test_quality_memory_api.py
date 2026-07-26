"""阶段十二质量反馈与用户记忆的认证、授权和隔离接口回归。"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.main import app
from app.models import Conversation, Message
from app.modules.auth.tokens import get_token_service
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user


def test_quality_and_memory_apis_enforce_user_and_admin_boundaries(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'quality-memory.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = create_test_user(factory, "quality-owner")
    other = create_test_user(factory, "quality-other")
    admin = create_test_user(factory, "quality-admin", role="admin")
    with factory() as session:
        conversation = Conversation(id="quality-conversation", user_id=owner.id)
        conversation.messages = [
            Message(
                id="quality-question",
                sequence=1,
                role="user",
                content="如何理解这份资料？",
                status="completed",
            ),
            Message(
                id="quality-answer",
                sequence=2,
                role="assistant",
                content="这是资料内的说明。",
                status="completed",
            ),
        ]
        session.add(conversation)
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/profile/memory-settings").status_code == 401
            assert client.get(
                "/api/v1/profile/memory-settings", headers=auth_headers(owner.id)
            ).json() == {"enabled": False}
            created_memory = client.post(
                "/api/v1/profile/memories",
                json={"label": "表达偏好", "content": "使用简洁中文"},
                headers=auth_headers(owner.id),
            )
            assert created_memory.status_code == 201
            assert client.get(
                "/api/v1/profile/memories", headers=auth_headers(other.id)
            ).json() == {"items": []}
            assert client.put(
                "/api/v1/profile/memory-settings",
                json={"enabled": True},
                headers=auth_headers(owner.id),
            ).json() == {"enabled": True}

            feedback = client.put(
                "/api/v1/quality/messages/quality-answer/feedback",
                json={
                    "rating": "down",
                    "question_category": "general",
                    "issue_category": "incomplete",
                    "comment": "缺少出处说明",
                },
                headers=auth_headers(owner.id),
            )
            assert feedback.status_code == 200
            feedback_id = feedback.json()["id"]
            assert client.put(
                "/api/v1/quality/messages/quality-answer/feedback",
                json={"rating": "up", "question_category": "general"},
                headers=auth_headers(other.id),
            ).status_code == 404
            assert client.get(
                "/api/v1/admin/quality/overview", headers=auth_headers(owner.id)
            ).status_code == 403
            assert client.get(
                "/api/v1/admin/quality/overview", headers=auth_headers(admin.id)
            ).json()["pending_review"] == 1
            detail = client.get(
                f"/api/v1/admin/quality/reviews/{feedback_id}",
                headers=auth_headers(admin.id),
            )
            assert detail.json()["question_excerpt"] == "如何理解这份资料？"
            reviewed = client.patch(
                f"/api/v1/admin/quality/reviews/{feedback_id}",
                json={"status": "resolved", "note": "已进入改进清单"},
                headers=auth_headers(admin.id),
            )
            assert reviewed.json()["review_status"] == "resolved"

            assert client.delete(
                f"/api/v1/profile/memories/{created_memory.json()['id']}",
                headers=auth_headers(other.id),
            ).status_code == 404
            assert client.delete(
                f"/api/v1/profile/memories/{created_memory.json()['id']}",
                headers=auth_headers(owner.id),
            ).status_code == 204
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
