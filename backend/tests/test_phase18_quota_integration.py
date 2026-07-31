"""阶段18共享链路：只用SQLite、Fake模型和Fake usage。"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.core.exceptions import RagServiceError
from app.main import app
from app.models import Conversation, Message, User
from app.modules.agent.repository import AgentRepository
from app.modules.agent.thread_repository import AgentThreadRepository
from app.modules.agent.thread_schemas import AgentMessageStreamRequest
from app.modules.audit.models import AuditEvent
from app.modules.auth.tokens import get_token_service
from app.modules.rag.ports import ModelUsage
from app.modules.usage.contracts import QuotaPolicyMode
from app.modules.usage.models import (
    ModelUsageRecord,
    QuotaPlan,
    QuotaPolicyEvent,
    QuotaReservation,
)
from app.modules.usage.quota_service import (
    DisabledQuotaGate,
    QuotaApplicationService,
    QuotaExceededError,
)
from app.modules.usage.estimator import (
    ConservativeQuotaReservationEstimator,
    QuotaReservationTooLargeError,
    RagReservationInput,
)
from app.ports.idempotency import IdempotencyRecord, IdempotencyStatus
from app.services.conversation_chat_service import ConversationChatService
from app.services.idempotency_service import IdempotencyClaim
from tests.auth_helpers import TEST_TOKEN_SERVICE, auth_headers, create_test_user
from tests.idempotency_helpers import AllowingIdempotency
from tests.test_agent_conversation_api import (
    AllowingAgentLock,
    RecordingAgentIdempotency,
    ReportPlanner,
    build_service,
)
from tests.test_conversation_chat_api import AllowingGenerationLock


class NoopMemory:
    def context_prefixes(self, user_id, conversation_id):
        del user_id, conversation_id
        return []

    def refresh_after_message(self, user_id, conversation_id):
        del user_id, conversation_id


class NoopContextProvider:
    def search(self, user_id, query, *, surface):
        del user_id, query, surface
        return SimpleNamespace(items=[])


class NoopScheduler:
    def schedule(self, *args, **kwargs):
        del args, kwargs


class RaisingScheduler:
    def schedule(self, *args, **kwargs):
        del args, kwargs
        raise RuntimeError("fake scheduler failure")


class CountingRag:
    model_name = "fake-chat"

    def __init__(self, usage=ModelUsage.actual(18, 4)):
        self.calls = 0
        self.usage = usage

    def ask_with_usage(self, question, top_k, history=None):
        del question, top_k, history
        self.calls += 1
        return "fake answer", [], self.usage


class FailingStreamRag:
    model_name = "fake-chat"

    async def astream_ask(self, question, top_k, history=None):
        del question, top_k, history
        yield {"event": "token", "data": {"content": "partial"}}
        raise RuntimeError("fake stream failure")


class RecordingConversationIdempotency:
    def __init__(self):
        self.record = None

    def begin(
        self, user_id, endpoint, client_request_id, conversation_id,
        question, top_k,
    ):
        del user_id, endpoint, client_request_id, conversation_id, question, top_k
        return IdempotencyClaim(
            "key",
            "fingerprint",
            self.record,
        )

    def complete(self, claim, **result):
        del claim
        self.record = IdempotencyRecord(
            status=IdempotencyStatus.COMPLETED,
            request_id=result["request_id"],
            conversation_id=result["conversation_id"],
            user_message_id=result["user_message_id"],
            assistant_message_id=result["assistant_message_id"],
        )

    def abandon(self, claim):
        del claim


def build_rag_fixture(token_limit):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = User(id="u", email="u@example.com", password_hash="x")
    conversation = Conversation(id="c", user_id="u", title="test")
    session.add_all([
        user,
        conversation,
        QuotaPlan(
            code="free",
            name="free",
            period_type="monthly",
            token_limit=token_limit,
            request_limit=10,
        ),
    ])
    session.commit()
    return engine, session, user, conversation


def add_maximum_rag_history(session, conversation_id):
    session.add_all([
        Message(
            conversation_id=conversation_id,
            sequence=1,
            role="user",
            content="中" * 3000,
            status="completed",
        ),
        Message(
            conversation_id=conversation_id,
            sequence=2,
            role="assistant",
            content="中" * 3000,
            status="completed",
        ),
    ])
    session.commit()


def build_rag_service(session, rag, scheduler=None, idempotency=None):
    return ConversationChatService(
        session,
        rag,
        AllowingGenerationLock(),
        idempotency or AllowingIdempotency(),
        memory=NoopMemory(),
        memory_context_provider=NoopContextProvider(),
        memory_extraction=scheduler or NoopScheduler(),
        quota_gate=QuotaApplicationService(session),
    )


def test_rag_quota_rejection_happens_before_fake_model_call():
    engine, session, user, conversation = build_rag_fixture(token_limit=100)
    rag = CountingRag()
    service = build_rag_service(
        session, rag, idempotency=RecordingConversationIdempotency()
    )
    with pytest.raises(QuotaExceededError):
        service.ask(user.id, conversation.id, "question", 3, "request-1")

    assert rag.calls == 0
    assert session.query(QuotaReservation).count() == 0
    assert [row.status for row in session.query(Message).order_by(Message.sequence)] == [
        "completed",
        "failed",
    ]
    session.close()
    engine.dispose()


def test_rag_shadow_mode_records_would_block_and_still_calls_fake_model():
    engine, session, user, conversation = build_rag_fixture(token_limit=100)
    rag = CountingRag()
    service = build_rag_service(
        session,
        rag,
        idempotency=RecordingConversationIdempotency(),
    )
    service.quota_gate = QuotaApplicationService(
        session,
        policy_mode=QuotaPolicyMode.SHADOW,
    )

    response = service.ask(
        user.id,
        conversation.id,
        "question",
        3,
        "shadow-rag",
    )

    assert response.answer == "fake answer"
    assert rag.calls == 1
    assert session.query(QuotaPolicyEvent).one().would_block is True
    assert session.query(QuotaReservation).one().status == "settled"
    session.close()
    engine.dispose()


def test_rag_actual_usage_settles_once_and_idempotent_replay_does_not_charge_twice():
    engine, session, user, conversation = build_rag_fixture(token_limit=10000)
    rag = CountingRag()
    service = build_rag_service(
        session, rag, idempotency=RecordingConversationIdempotency()
    )
    first = service.ask(user.id, conversation.id, "question", 3, "same")
    replay = service.ask(user.id, conversation.id, "question", 3, "same")

    assert first.assistant_message_id == replay.assistant_message_id
    assert rag.calls == 1
    reservation = session.query(QuotaReservation).one()
    assert reservation.status == "settled"
    assert reservation.charged_tokens == 22
    assert first.usage.total_tokens == 22
    assert first.usage.charged_tokens == 22
    assert service.quota_gate.current(user.id)["used_tokens"] == 22
    session.close()
    engine.dispose()


def test_memory_schedule_failure_does_not_change_completed_rag_answer():
    engine, session, user, conversation = build_rag_fixture(token_limit=10000)
    rag = CountingRag()
    response = build_rag_service(
        session, rag, RaisingScheduler()
    ).ask(
        user.id,
        conversation.id,
        "请记住我的偏好",
        3,
        "schedule-failure",
    )
    assistant = session.get(Message, response.assistant_message_id)
    assert assistant.status == "completed"
    assert assistant.content == "fake answer"
    assert rag.calls == 1
    session.close()
    engine.dispose()


def test_failed_rag_stream_with_unknown_usage_charges_reservation():
    engine, session, user, conversation = build_rag_fixture(token_limit=10000)
    service = build_rag_service(session, FailingStreamRag())
    iterator = service.stream(
        user.id,
        conversation.id,
        "question",
        3,
        "server-request",
        "failed-stream",
    )

    async def consume():
        events = []
        with pytest.raises(RagServiceError):
            async for event in iterator:
                events.append(event)
        return events

    assert asyncio.run(consume())[0]["event"] == "token"
    reservation = session.query(QuotaReservation).one()
    usage = session.query(ModelUsageRecord).one()
    assert reservation.status == "settled"
    assert reservation.charged_tokens == reservation.reserved_tokens
    assert reservation.charged_tokens > 4000
    assert usage.token_measurement == "unknown"
    assert usage.status == "failed"
    assert service._usage_summary(
        session.query(Message).filter_by(role="assistant").one().id
    ).charged_tokens == reservation.reserved_tokens
    assert session.query(Message).filter_by(role="assistant").one().status == "failed"
    session.close()
    engine.dispose()


def test_rag_estimator_grows_for_history_chunks_and_memory_but_keeps_short_minimum():
    estimator = ConservativeQuotaReservationEstimator()
    base = dict(
        system_prompt="system",
        question="short",
        top_k=1,
        chunk_char_budget=100,
        source_wrapper_tokens=20,
        max_output_tokens=500,
    )
    short = estimator.estimate_rag(
        RagReservationInput(history=(), **base)
    )
    long_context = estimator.estimate_rag(
        RagReservationInput(
            history=(
                ("user", "既往对话" * 500),
                ("user", "用户可编辑背景" * 300),
            ),
            **{**base, "top_k": 8},
        )
    )

    assert short.requested_tokens == 4000
    assert long_context.requested_tokens > short.requested_tokens
    assert long_context.estimation_method == "conservative_chars_v1"


def test_rag_context_too_large_is_rejected_before_fake_model_call():
    engine, session, user, conversation = build_rag_fixture(token_limit=1_000_000)
    add_maximum_rag_history(session, conversation.id)
    rag = CountingRag()
    service = build_rag_service(
        session, rag, idempotency=RecordingConversationIdempotency()
    )

    with pytest.raises(QuotaReservationTooLargeError):
        service.ask(user.id, conversation.id, "中" * 2000, 10, "too-large")

    assert rag.calls == 0
    assert session.query(QuotaReservation).count() == 0
    assert session.query(Message).filter_by(sequence=4).one().status == "failed"
    session.close()
    engine.dispose()


def test_rag_off_mode_skips_estimator_and_preserves_long_request_behavior():
    engine, session, user, conversation = build_rag_fixture(token_limit=1_000_000)
    add_maximum_rag_history(session, conversation.id)
    rag = CountingRag()
    service = build_rag_service(
        session, rag, idempotency=RecordingConversationIdempotency()
    )
    service.quota_gate = DisabledQuotaGate(
        QuotaApplicationService(session, policy_mode=QuotaPolicyMode.OFF)
    )

    response = service.ask(
        user.id,
        conversation.id,
        "中" * 2000,
        10,
        "off-long-context",
    )

    assert response.answer == "fake answer"
    assert rag.calls == 1
    assert session.query(QuotaReservation).count() == 0
    assert session.query(QuotaPolicyEvent).count() == 0
    session.close()
    engine.dispose()


def test_rag_shadow_mode_observes_long_estimate_without_blocking_model():
    engine, session, user, conversation = build_rag_fixture(token_limit=10_000)
    add_maximum_rag_history(session, conversation.id)
    rag = CountingRag()
    service = build_rag_service(
        session, rag, idempotency=RecordingConversationIdempotency()
    )
    service.quota_gate = QuotaApplicationService(
        session,
        policy_mode=QuotaPolicyMode.SHADOW,
    )

    response = service.ask(
        user.id,
        conversation.id,
        "中" * 2000,
        10,
        "shadow-long-context",
    )

    event = session.query(QuotaPolicyEvent).filter_by(
        idempotency_key="rag:shadow-long-context"
    ).one()
    reservation = session.query(QuotaReservation).one()
    assert response.answer == "fake answer"
    assert rag.calls == 1
    assert event.would_block is True
    assert reservation.reserved_tokens > 20_000
    assert reservation.status == "settled"
    session.close()
    engine.dispose()


class CountingPlanner(ReportPlanner):
    def __init__(self):
        self.calls = 0

    def classify_and_plan(self, state):
        self.calls += 1
        return super().classify_and_plan(state)


class RaisingReservationEstimator:
    def estimate_agent(self, value):
        del value
        raise AssertionError("off mode must not estimate an Agent reservation")


def test_agent_quota_rejection_happens_before_planner_or_model():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(id="u", email="u@example.com", password_hash="x")
        session.add_all([
            user,
            QuotaPlan(
                code="free",
                name="free",
                period_type="monthly",
                token_limit=100,
                request_limit=10,
            ),
        ])
        session.flush()
        thread = AgentThreadRepository(session).create_thread(user_id=user.id)
        session.commit()
        planner = CountingPlanner()
        service = build_service(
            session,
            AllowingAgentLock(),
            RecordingAgentIdempotency(),
            planner,
        )
        service.quota_gate = QuotaApplicationService(session)

        with pytest.raises(QuotaExceededError):
            list(service.stream_message(
                user_id=user.id,
                thread_id=thread.id,
                payload=AgentMessageStreamRequest(content="生成报告"),
                client_request_id="quota-reject",
                request_id="request",
            ))

        assert planner.calls == 0
        assert session.query(QuotaReservation).count() == 0
        assert AgentRepository(session).list_runs(user.id)[0].status == "failed"
    engine.dispose()


def test_agent_off_mode_skips_reservation_estimator():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(id="u", email="u@example.com", password_hash="x")
        session.add_all([
            user,
            QuotaPlan(
                code="free",
                name="free",
                period_type="monthly",
                token_limit=1_000_000,
                request_limit=500,
            ),
        ])
        session.flush()
        thread = AgentThreadRepository(session).create_thread(user_id=user.id)
        session.commit()
        service = build_service(
            session,
            AllowingAgentLock(),
            RecordingAgentIdempotency(),
        )
        service.quota_gate = DisabledQuotaGate(
            QuotaApplicationService(session, policy_mode=QuotaPolicyMode.OFF)
        )
        service.quota_estimator = RaisingReservationEstimator()

        events = list(service.stream_message(
            user_id=user.id,
            thread_id=thread.id,
            payload=AgentMessageStreamRequest(content="生成报告"),
            client_request_id="agent-off",
            request_id="request",
        ))

        assert any(item["event"] == "message_completed" for item in events)
        assert session.query(QuotaReservation).count() == 0
        assert session.query(QuotaPolicyEvent).count() == 0
    engine.dispose()


class DisconnectingAgentRunner:
    model_name = "fake-agent"

    def __init__(self, session):
        self.session = session

    def stream_run(self, user_id, run_id, *, task_context):
        del task_context
        yield {"event": "run_started", "data": {"run_id": run_id}}
        try:
            yield {"event": "token", "data": {"content": "partial"}}
        except GeneratorExit:
            run = AgentRepository(self.session).get_run(user_id, run_id)
            self.session.add(ModelUsageRecord(
                call_id=f"agent:{run_id}:fake:1",
                user_id=user_id,
                surface="agent",
                operation="final_answer",
                model_name=self.model_name,
                input_tokens=7,
                output_tokens=5,
                total_tokens=12,
                token_measurement="actual",
                usage_group_id=run.response_message_id,
                status="cancelled",
            ))
            self.session.commit()
            raise


def test_agent_disconnect_settles_usage_recorded_before_stream_close():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = User(id="u", email="u@example.com", password_hash="x")
        session.add_all([
            user,
            QuotaPlan(
                code="free",
                name="free",
                period_type="monthly",
                token_limit=20000,
                request_limit=10,
            ),
        ])
        session.flush()
        thread = AgentThreadRepository(session).create_thread(user_id=user.id)
        session.commit()
        service = build_service(
            session,
            AllowingAgentLock(),
            RecordingAgentIdempotency(),
        )
        service.quota_gate = QuotaApplicationService(session)
        service.agent = DisconnectingAgentRunner(session)
        iterator = service.stream_message(
            user_id=user.id,
            thread_id=thread.id,
            payload=AgentMessageStreamRequest(content="生成报告"),
            client_request_id="disconnect-usage",
            request_id="request",
        )
        assert next(iterator)["event"] == "message_created"
        assert next(iterator)["event"] == "run_started"
        assert next(iterator)["event"] == "token"
        iterator.close()

        reservation = session.query(QuotaReservation).one()
        assert reservation.status == "settled"
        assert reservation.charged_tokens == 12
        messages = AgentThreadRepository(session).list_messages(
            user.id, thread.id
        )
        assert messages[-1].status == "stopped"
    engine.dispose()


def test_profile_usage_is_user_isolated_and_quota_adjustment_is_audited(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'usage-api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    user_a = create_test_user(factory, "usage-a")
    user_b = create_test_user(factory, "usage-b")
    admin = create_test_user(factory, "usage-admin", role="admin")
    super_admin = create_test_user(
        factory, "usage-super", role="super_admin"
    )
    with factory() as session:
        session.add(QuotaPlan(
            code="free",
            name="free",
            period_type="monthly",
            token_limit=5000,
            request_limit=20,
        ))
        session.add_all([
            ModelUsageRecord(
                call_id="a", user_id=user_a.id, surface="rag",
                operation="answer", model_name="fake",
                input_tokens=2, output_tokens=1, total_tokens=3,
                token_measurement="actual",
            ),
            ModelUsageRecord(
                call_id="b", user_id=user_b.id, surface="agent",
                operation="answer", model_name="fake",
                token_measurement="unknown",
            ),
        ])
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_token_service] = lambda: TEST_TOKEN_SERVICE
    try:
        with TestClient(app) as client:
            own = client.get(
                "/api/v1/profile/usage/records",
                headers=auth_headers(user_a.id),
            )
            assert own.status_code == 200
            assert [item["user_id"] for item in own.json()["items"]] == [
                user_a.id
            ]

            payload = {
                "token_limit_override": 9000,
                "request_limit_override": 30,
                "estimated_cost_limit_cny_override": 12.5,
                "reason": "本地阶段18测试",
            }
            denied = client.put(
                f"/api/v1/admin/users/{user_a.id}/quota",
                json=payload,
                headers=auth_headers(admin.id),
            )
            assert denied.status_code == 403

            adjusted = client.put(
                f"/api/v1/admin/users/{user_a.id}/quota",
                json=payload,
                headers=auth_headers(super_admin.id),
            )
            assert adjusted.status_code == 200
            assert adjusted.json()["token_limit"] == 9000
            assert adjusted.json()["estimated_cost_limit_cny"] == 12.5
            restored = client.put(
                f"/api/v1/admin/users/{user_a.id}/quota",
                json={
                    "token_limit_override": None,
                    "request_limit_override": None,
                    "estimated_cost_limit_cny_override": None,
                    "reason": "恢复默认额度",
                },
                headers=auth_headers(super_admin.id),
            )
            assert restored.status_code == 200
            assert restored.json()["token_limit"] == 5000
            assert restored.json()["request_limit"] == 20
            assert restored.json()["estimated_cost_limit_cny"] is None

        with factory() as session:
            audits = session.query(AuditEvent).order_by(AuditEvent.created_at).all()
            assert len(audits) == 2
            audit = audits[0]
            assert audit.action == "user.quota.adjust"
            assert audit.actor_user_id == super_admin.id
            assert audit.object_id == user_a.id
            assert audit.details["reason"] == "本地阶段18测试"
            assert audit.details["after_cost_limit"] == "12.5"
            assert audits[1].details["reason"] == "恢复默认额度"
            assert audits[1].details["after_cost_limit"] is None
            assert session.get(User, user_a.id).role == "user"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
