from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.usage.contracts import (
    ModelUsage,
    QuotaPolicyMode,
    resolve_quota_policy_mode,
)
from app.modules.usage.models import (
    ModelUsageRecord,
    QuotaPeriod,
    QuotaPlan,
    QuotaPolicyEvent,
    QuotaReservation,
)
from app.modules.usage.quota_service import (
    DisabledQuotaGate,
    QuotaApplicationService,
    QuotaExceededError,
    QuotaPolicyUnavailableError,
)
from app.modules.usage.estimator import (
    AgentReservationInput,
    ConservativeQuotaReservationEstimator,
)


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
        "QUOTA_RAG_MAX_OUTPUT_TOKENS": "2000",
        "QUOTA_RAG_SOURCE_WRAPPER_TOKENS": "200",
    }

    for name, value in defaults.items():
        assert f"{name}: ${{{name}:-{value}}}" in compose_text
        assert f"{name}={value}" in backend_example
        assert f"{name}={value}" in deploy_example
    assert "QUOTA_POLICY_MODE: ${QUOTA_POLICY_MODE:-}" in compose_text
    assert "QUOTA_POLICY_MODE=off" in backend_example
    assert "QUOTA_POLICY_MODE=off" in deploy_example


def test_quota_policy_mode_prefers_new_config_and_maps_legacy_boolean():
    assert resolve_quota_policy_mode(None, False) is QuotaPolicyMode.OFF
    assert resolve_quota_policy_mode(None, True) is QuotaPolicyMode.ENFORCE
    assert resolve_quota_policy_mode("shadow", True) is QuotaPolicyMode.SHADOW

    settings = Settings(
        _env_file=None,
        quota_policy_mode=" SHADOW ",
        quota_enforcement_enabled=True,
    )
    assert settings.quota_policy_mode == "shadow"


def test_missing_plan_uses_v2_default_limits():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(User(id="no-plan", email="no-plan@example.com", password_hash="x"))
    session.commit()

    current = QuotaApplicationService(session).current("no-plan")

    assert current["token_limit"] == 1_000_000
    assert current["request_limit"] == 500
    session.close()
    engine.dispose()


def test_off_mode_creates_period_without_reservation_or_policy_event():
    engine, session = build()
    gate = DisabledQuotaGate(
        QuotaApplicationService(
            session,
            policy_mode=QuotaPolicyMode.OFF,
        )
    )

    assert gate.reserve("u", "rag", "off-request", 10_000, "group") is None
    assert session.query(QuotaPeriod).count() == 1
    assert session.query(QuotaReservation).count() == 0
    assert session.query(QuotaPolicyEvent).count() == 0
    session.close()
    engine.dispose()


def test_shadow_records_would_block_but_reserves_and_is_idempotent():
    engine, session = build()
    service = QuotaApplicationService(
        session,
        policy_mode=QuotaPolicyMode.SHADOW,
    )

    first = service.reserve("u", "rag", "shadow-request", 120, "group")
    replay = service.reserve("u", "rag", "shadow-request", 120, "group")
    event = session.query(QuotaPolicyEvent).one()

    assert replay.id == first.id
    assert event.would_block is True
    assert event.reason_code == "TOKEN_LIMIT_EXCEEDED"
    assert event.requested_tokens == 120
    assert event.remaining_tokens == 100
    assert session.query(QuotaReservation).count() == 1
    service.settle(first.id, ModelUsage.actual(10, 5))
    assert service.current("u")["used_tokens"] == 15
    session.close()
    engine.dispose()


def test_enforce_persists_one_block_event_without_reservation():
    engine, session = build()
    service = QuotaApplicationService(
        session,
        policy_mode=QuotaPolicyMode.ENFORCE,
    )

    for _ in range(2):
        with pytest.raises(QuotaExceededError):
            service.reserve("u", "rag", "blocked-request", 120, "group")

    event = session.query(QuotaPolicyEvent).one()
    assert event.policy_mode == "enforce"
    assert event.would_block is True
    assert event.reason_code == "TOKEN_LIMIT_EXCEEDED"
    assert session.query(QuotaReservation).count() == 0
    session.close()
    engine.dispose()


def test_enforce_records_request_limit_reason():
    engine, session = build()
    service = QuotaApplicationService(
        session,
        policy_mode=QuotaPolicyMode.ENFORCE,
    )
    period = service.ensure_period("u")
    period.used_requests = period.request_limit
    session.commit()

    with pytest.raises(QuotaExceededError):
        service.reserve("u", "agent", "request-limit", 10, "group")

    assert session.query(QuotaPolicyEvent).one().reason_code == (
        "REQUEST_LIMIT_EXCEEDED"
    )
    session.close()
    engine.dispose()


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


def test_agent_estimator_can_lower_reservation_but_never_exceeds_policy_limit():
    estimator = ConservativeQuotaReservationEstimator()
    short = estimator.estimate_agent(
        AgentReservationInput(
            rendered_context="生成报告",
            estimated_context_tokens=3,
            max_output_tokens=1200,
            policy_token_limit=12000,
        )
    )
    large = estimator.estimate_agent(
        AgentReservationInput(
            rendered_context="长上下文" * 10000,
            estimated_context_tokens=30000,
            max_output_tokens=1200,
            policy_token_limit=12000,
        )
    )

    assert 2200 <= short.requested_tokens < 12000
    assert large.requested_tokens == 12000


def test_actual_over_reservation_is_fully_charged_and_records_underestimate():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.token_limit = 500
    session.commit()
    service = QuotaApplicationService(session)
    reservation = service.reserve("u", "rag", "under", 80)

    settled = service.settle(reservation.id, ModelUsage.actual(90, 30))

    assert settled.charged_tokens == 120
    assert service.current("u")["used_tokens"] == 120
    event = session.query(QuotaPolicyEvent).filter_by(
        reason_code="RESERVATION_UNDERESTIMATED"
    ).one()
    assert event.requested_tokens == 120
    assert service.metrics()["reservation_underestimated_events"] == 1
    session.close(); engine.dispose()


def test_optional_cost_limit_blocks_only_when_configured_and_reliably_priced():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.token_limit = 10_000
    plan.estimated_cost_limit_cny = Decimal("0.001")
    session.commit()
    service = QuotaApplicationService(session)

    with pytest.raises(QuotaExceededError):
        service.reserve(
            "u",
            "rag",
            "cost-limit",
            1000,
            estimated_input_tokens=800,
            estimated_output_tokens=200,
            input_price_per_million_tokens_cny=2,
            output_price_per_million_tokens_cny=10,
        )

    event = session.query(QuotaPolicyEvent).filter_by(
        idempotency_key="cost-limit"
    ).one()
    assert event.reason_code == "COST_LIMIT_EXCEEDED"
    assert event.requested_estimated_cost_cny == Decimal("0.00360000")
    session.close(); engine.dispose()


def test_enforce_cost_limit_without_prices_returns_policy_unavailable():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.estimated_cost_limit_cny = Decimal("1")
    session.commit()
    service = QuotaApplicationService(session)

    with pytest.raises(QuotaPolicyUnavailableError):
        service.reserve(
            "u",
            "rag",
            "missing-price",
            80,
            estimated_input_tokens=50,
            estimated_output_tokens=30,
        )

    assert session.query(QuotaReservation).count() == 0
    assert session.query(QuotaPolicyEvent).one().reason_code == (
        "QUOTA_POLICY_UNAVAILABLE"
    )
    session.close(); engine.dispose()


def test_shadow_cost_policy_unavailable_records_and_continues():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.estimated_cost_limit_cny = Decimal("1")
    session.commit()
    service = QuotaApplicationService(
        session,
        policy_mode=QuotaPolicyMode.SHADOW,
    )

    reservation = service.reserve(
        "u",
        "agent",
        "shadow-missing-price",
        80,
        estimated_input_tokens=50,
        estimated_output_tokens=30,
    )

    assert reservation.status == "reserved"
    assert reservation.reserved_estimated_cost_cny is None
    assert session.query(QuotaPolicyEvent).one().would_block is True
    service.release(reservation.id)
    session.close(); engine.dispose()


def test_priced_reservation_tracks_actual_cost_and_unknown_uses_reserved_cost():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.token_limit = 500
    plan.estimated_cost_limit_cny = Decimal("1")
    session.commit()
    service = QuotaApplicationService(session)
    actual = service.reserve(
        "u", "rag", "priced-actual", 100,
        estimated_input_tokens=80,
        estimated_output_tokens=20,
        input_price_per_million_tokens_cny=2,
        output_price_per_million_tokens_cny=10,
    )
    unknown = service.reserve(
        "u", "agent", "priced-unknown", 100,
        estimated_input_tokens=70,
        estimated_output_tokens=30,
        input_price_per_million_tokens_cny=2,
        output_price_per_million_tokens_cny=10,
    )

    service.settle(actual.id, ModelUsage.actual(40, 10))
    service.settle(unknown.id, ModelUsage.unknown())
    session.refresh(actual)
    session.refresh(unknown)

    assert actual.charged_estimated_cost_cny == Decimal("0.00018000")
    assert unknown.charged_estimated_cost_cny == Decimal("0.00044000")
    current = service.current("u")
    assert current["used_estimated_cost_cny"] == pytest.approx(0.00062)
    assert current["reserved_estimated_cost_cny"] == 0
    session.close(); engine.dispose()


def test_quota_warning_levels_and_remaining_question_estimate_use_settled_samples():
    engine, session = build()
    plan = session.query(QuotaPlan).one()
    plan.token_limit = 1000
    plan.request_limit = 10
    session.commit()
    service = QuotaApplicationService(session)
    for index, charged in enumerate((100, 100, 100), start=1):
        reservation = service.reserve("u", "rag", f"sample-{index}", 100)
        service.settle(reservation.id, ModelUsage.actual(charged - 10, 10))

    current = service.current("u")
    assert current["warning_level"] == "normal"
    assert current["estimated_remaining_requests"] == 7

    period = session.query(QuotaPeriod).one()
    period.used_tokens = 800
    session.commit()
    assert service.current("u")["warning_level"] == "warning"
    period.used_tokens = 950
    session.commit()
    assert service.current("u")["warning_level"] == "critical"
    period.used_tokens = 1000
    session.commit()
    assert service.current("u")["warning_level"] == "exhausted"
    session.close(); engine.dispose()
