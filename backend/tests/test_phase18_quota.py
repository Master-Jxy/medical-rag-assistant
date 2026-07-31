from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.usage.contracts import ModelUsage
from app.modules.usage.models import ModelUsageRecord, QuotaPlan
from app.modules.usage.quota_service import QuotaApplicationService, QuotaExceededError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_phase17_and_phase18_flags_are_explicitly_wired_for_deployment():
    compose_text = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    backend_example = (PROJECT_ROOT / "backend" / ".env.example").read_text(
        encoding="utf-8"
    )
    deploy_example = (PROJECT_ROOT / "deploy" / ".env.example").read_text(
        encoding="utf-8"
    )
    defaults = {
        "MEMORY_AUTO_EXTRACTION_ENABLED": "false",
        "MEMORY_EXTRACTION_INTERVAL_TURNS": "3",
        "MEMORY_RAG_MAX_ITEMS": "4",
        "MEMORY_AGENT_MAX_ITEMS": "6",
        "QUOTA_ENFORCEMENT_ENABLED": "false",
        "DEFAULT_QUOTA_PLAN_CODE": "free",
        "QUOTA_RAG_RESERVE_TOKENS": "4000",
        "QUOTA_AGENT_RESERVE_TOKENS": "12000",
    }

    for name, value in defaults.items():
        assert f"{name}: ${{{name}:-{value}}}" in compose_text
        assert f"{name}={value}" in backend_example
        assert f"{name}={value}" in deploy_example


def build():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(User(id="u", email="u@example.com", password_hash="x"))
    session.add(QuotaPlan(code="free", name="free", period_type="monthly", token_limit=100, request_limit=2))
    session.commit()
    return engine, session


def test_reservation_is_idempotent_and_actual_usage_returns_difference():
    engine, session = build()
    service = QuotaApplicationService(session)
    first = service.reserve("u", "rag", "same", 80)
    assert service.reserve("u", "rag", "same", 80).id == first.id
    settled = service.settle(first.id, ModelUsage.actual(20, 10))
    assert settled.charged_tokens == 30
    assert service.current("u")["remaining_tokens"] == 70
    session.close(); engine.dispose()


def test_unknown_charges_reservation_and_insufficient_quota_blocks():
    engine, session = build()
    service = QuotaApplicationService(session)
    reserved = service.reserve("u", "agent", "one", 80)
    service.settle(reserved.id, ModelUsage.unknown())
    try:
        service.reserve("u", "rag", "two", 30)
    except QuotaExceededError:
        pass
    else:
        raise AssertionError("quota must reject before model call")
    session.close(); engine.dispose()


def test_not_applicable_releases_reserved_capacity_and_charges_zero():
    engine, session = build()
    service = QuotaApplicationService(session)
    reservation = service.reserve("u", "rag", "no-model", 80)
    settled = service.settle(reservation.id, ModelUsage.not_applicable())
    current = service.current("u")

    assert settled.status == "settled"
    assert settled.charged_tokens == 0
    assert current["used_tokens"] == 0
    assert current["used_requests"] == 0
    assert current["reserved_tokens"] == 0
    assert current["remaining_tokens"] == 100
    session.close(); engine.dispose()


def test_expired_reservations_settle_from_ledger_or_release_without_ledger():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.token_limit = 500
    plan.request_limit = 10
    session.commit()
    service = QuotaApplicationService(session)
    with_usage = service.reserve("u", "rag", "with-usage", 80, "group-1")
    without_usage = service.reserve("u", "agent", "without-usage", 70, "group-2")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with_usage.expires_at = past
    without_usage.expires_at = past
    session.add(ModelUsageRecord(
        call_id="expired-actual",
        user_id="u",
        surface="rag",
        operation="answer",
        model_name="fake",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        token_measurement="actual",
        usage_group_id="group-1",
    ))
    session.commit()

    assert service.reconcile_expired(user_id="u") == {
        "settled": 1,
        "released": 1,
    }
    session.refresh(with_usage)
    session.refresh(without_usage)
    assert with_usage.status == "settled"
    assert with_usage.charged_tokens == 15
    assert without_usage.status == "released"
    assert service.current("u")["used_tokens"] == 15
    session.close(); engine.dispose()
