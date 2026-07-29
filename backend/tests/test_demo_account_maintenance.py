"""任务16.1e：演示账号清理预检、保护闸门和临时库执行。"""

from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models.conversation import Conversation, Message
from app.maintenance.demo_accounts import (
    DEMO_ACCOUNT_CONFIRM_PHRASE,
    DemoAccountCleanupBlockedError,
    DemoAccountMaintenanceService,
    cleanup_plan_as_dict,
)
from app.modules.auth.models import User
from app.modules.knowledge.models import KnowledgeDocument, KnowledgeSubmission
from app.modules.usage.models import ModelUsageRecord


def build_maintenance_engine():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        owner = User(
            id="owner",
            email="owner@example.com",
            password_hash="hash",
            role="super_admin",
            is_active=True,
            email_verified_at=now,
        )
        target = User(
            id="demo",
            email="demo@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
            email_verified_at=now,
        )
        conversation = Conversation(id="conversation", user_id=target.id)
        message = Message(
            id="message",
            conversation_id=conversation.id,
            sequence=1,
            role="user",
            content="temporary",
            status="completed",
        )
        document = KnowledgeDocument(
            id="document",
            original_name="public.txt",
            stored_name="public-stored.txt",
            content_hash="a" * 64,
            size_bytes=10,
            chunk_count=1,
            chunk_ids=["chunk-1"],
            uploader_id=target.id,
            is_system=False,
            status="published",
        )
        published = KnowledgeSubmission(
            id="published",
            submitter_id=target.id,
            original_name="public.txt",
            stored_name="published.txt",
            content_hash="b" * 64,
            size_bytes=10,
            status="published",
            document_id=document.id,
        )
        pending = KnowledgeSubmission(
            id="pending",
            submitter_id=target.id,
            original_name="pending.txt",
            stored_name="pending.txt",
            content_hash="c" * 64,
            size_bytes=10,
            status="pending_review",
        )
        session.add_all(
            [owner, target, conversation, message, document, published, pending]
        )
        session.add(
            ModelUsageRecord(
                id="usage",
                call_id="rag:message:answer",
                user_id=target.id,
                surface="rag",
                operation="answer",
                model_name="fake",
                input_tokens=10,
                output_tokens=2,
                total_tokens=12,
                token_measurement="actual",
            )
        )
        session.commit()
    return engine


def test_preflight_is_read_only_and_returns_deterministic_exact_plan() -> None:
    engine = build_maintenance_engine()
    with Session(engine) as session:
        before = {
            "users": session.scalar(select(func.count()).select_from(User)),
            "documents": session.scalar(
                select(func.count()).select_from(KnowledgeDocument)
            ),
            "submissions": session.scalar(
                select(func.count()).select_from(KnowledgeSubmission)
            ),
            "conversations": session.scalar(
                select(func.count()).select_from(Conversation)
            ),
        }
        plan = DemoAccountMaintenanceService(session).preflight(
            " OWNER@example.com "
        )
        again = DemoAccountMaintenanceService(session).preflight(
            "owner@example.com"
        )
        after = {
            "users": session.scalar(select(func.count()).select_from(User)),
            "documents": session.scalar(
                select(func.count()).select_from(KnowledgeDocument)
            ),
            "submissions": session.scalar(
                select(func.count()).select_from(KnowledgeSubmission)
            ),
            "conversations": session.scalar(
                select(func.count()).select_from(Conversation)
            ),
        }

    assert plan.users_total == 2
    assert plan.users_to_delete == 1
    assert plan.public_documents_to_transfer == 1
    assert plan.public_submissions_to_transfer == 1
    assert plan.personal_submissions_to_delete == 1
    assert plan.conversations_to_delete == 1
    assert plan.usage_records_to_anonymize == 1
    assert plan.fingerprint == again.fingerprint
    assert before == after
    assert json.dumps(cleanup_plan_as_dict(plan), ensure_ascii=False)


@pytest.mark.parametrize(
    ("confirmation", "fingerprint"),
    [
        ("wrong", "unused"),
        (DEMO_ACCOUNT_CONFIRM_PHRASE, "stale-fingerprint"),
    ],
)
def test_execute_rejects_wrong_phrase_or_changed_plan_without_writes(
    confirmation: str, fingerprint: str
) -> None:
    engine = build_maintenance_engine()
    with Session(engine) as session:
        service = DemoAccountMaintenanceService(session)
        before = service.preflight("owner@example.com")
        with pytest.raises(DemoAccountCleanupBlockedError):
            service.execute(
                "owner@example.com",
                expected_fingerprint=fingerprint,
                confirmation=confirmation,
            )
        assert service.preflight("owner@example.com").fingerprint == before.fingerprint


def test_temp_database_cleanup_transfers_public_assets_and_deletes_personal_data() -> None:
    engine = build_maintenance_engine()
    with Session(engine) as session:
        service = DemoAccountMaintenanceService(session)
        plan = service.preflight("owner@example.com")
        service.execute(
            "owner@example.com",
            expected_fingerprint=plan.fingerprint,
            confirmation=DEMO_ACCOUNT_CONFIRM_PHRASE,
        )

    with Session(engine) as session:
        assert session.scalars(select(User.id)).all() == ["owner"]
        document = session.get(KnowledgeDocument, "document")
        published = session.get(KnowledgeSubmission, "published")
        assert document is not None and document.uploader_id == "owner"
        assert published is not None and published.submitter_id == "owner"
        assert session.get(KnowledgeSubmission, "pending") is None
        assert session.get(Conversation, "conversation") is None
        assert session.get(Message, "message") is None
        usage = session.get(ModelUsageRecord, "usage")
        assert usage is not None and usage.user_id is None


def test_preflight_stops_on_unknown_user_foreign_key() -> None:
    engine = build_maintenance_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE unexpected_user_links ("
                "id INTEGER PRIMARY KEY, "
                "user_id VARCHAR(36) REFERENCES users(id))"
            )
        )

    with Session(engine) as session:
        with pytest.raises(
            DemoAccountCleanupBlockedError,
            match="unexpected_user_links.user_id",
        ):
            DemoAccountMaintenanceService(session).preflight(
                "owner@example.com"
            )


@pytest.mark.parametrize(
    ("role", "active", "verified"),
    [
        ("admin", True, True),
        ("super_admin", False, True),
        ("super_admin", True, False),
    ],
)
def test_owner_must_be_active_verified_super_admin(
    role: str, active: bool, verified: bool
) -> None:
    engine = build_maintenance_engine()
    with Session(engine) as session:
        owner = session.get(User, "owner")
        assert owner is not None
        owner.role = role
        owner.is_active = active
        owner.email_verified_at = (
            datetime.now(timezone.utc) if verified else None
        )
        session.commit()
        with pytest.raises(DemoAccountCleanupBlockedError):
            DemoAccountMaintenanceService(session).preflight(
                "owner@example.com"
            )
