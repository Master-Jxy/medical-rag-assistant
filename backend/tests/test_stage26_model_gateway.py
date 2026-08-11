"""Stage 26.6 model gateway, routing and quota safety tests using Fake calls."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.modules.auth.models import User
from app.modules.model_gateway.contracts import (
    ModelCapability,
    ModelFailureKind,
    ModelQuotaRejectedError,
    ModelRoute,
    ModelRouteRequest,
    ModelSelectionError,
    ModelSurface,
    ProviderCallConsumedError,
    ProviderCallResult,
)
from app.modules.model_gateway.gateway import (
    ModelRouteHealthRegistry,
    StaticModelGateway,
    classify_model_failure,
)
from app.modules.model_gateway.coverage import accounting_contracts
from app.modules.model_gateway.policy import StaticModelRoutePolicy
from app.modules.usage.contracts import ModelUsage, QuotaPolicyMode
from app.modules.usage.models import QuotaPlan, QuotaReservation
from app.modules.usage.quota_service import QuotaApplicationService, QuotaExceededError


def route(route_id: str, *, capabilities=None, minimum_role="user") -> ModelRoute:
    return ModelRoute(
        id=route_id,
        label=route_id,
        provider="dashscope",
        model_name=f"fake-{route_id}",
        capabilities=frozenset(capabilities or {ModelCapability.TEXT}),
        surfaces=frozenset({ModelSurface.RAG}),
        enabled=True,
        user_selectable=True,
        minimum_role=minimum_role,
    )


def request(**changes) -> ModelRouteRequest:
    values = {
        "surface": ModelSurface.RAG,
        "task_kind": "answer",
        "required_capabilities": frozenset({ModelCapability.TEXT}),
        "user_role": "user",
    }
    values.update(changes)
    return ModelRouteRequest(**values)


class FakeProviderError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def test_transient_consumed_failure_falls_back_once_and_bills_both_attempts() -> None:
    primary = route("primary")
    fallback = route("fallback")
    policy = StaticModelRoutePolicy(
        (primary, fallback),
        defaults={ModelSurface.RAG: primary.id},
        fallbacks={primary.id: fallback.id},
    )
    health = ModelRouteHealthRegistry()
    gateway = StaticModelGateway(policy, health=health)
    calls: list[str] = []
    usage_events = []

    def fake_call(active_route):
        calls.append(active_route.id)
        if active_route.id == "primary":
            raise ProviderCallConsumedError(
                "temporary provider failure",
                usage=ModelUsage.actual(8, 2),
                provider_code="SERVICE_UNAVAILABLE",
            )
        return ProviderCallResult("ok", ModelUsage.actual(6, 4))

    result = gateway.invoke(
        request(),
        usage_group_id="answer-1",
        call=fake_call,
        usage_sink=usage_events.append,
    )

    assert result.value == "ok"
    assert result.attempts == 2
    assert calls == ["primary", "fallback"]
    assert [event.usage_group_id for event in usage_events] == ["answer-1", "answer-1"]
    assert [event.usage.total_tokens for event in usage_events] == [10, 10]
    assert [event.status for event in usage_events] == ["failed", "completed"]
    assert health.snapshot()[1]["fallback_route_id"] == "fallback"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (ValueError("bad input"), ModelFailureKind.INVALID_REQUEST),
        (QuotaExceededError(), ModelFailureKind.QUOTA_REJECTED),
        (FakeProviderError("CONTENT_FILTER", 503), ModelFailureKind.SAFETY_REJECTION),
    ],
)
def test_non_transient_failures_never_fallback(error, kind) -> None:
    primary = route("primary")
    fallback = route("fallback")
    gateway = StaticModelGateway(StaticModelRoutePolicy(
        (primary, fallback),
        defaults={ModelSurface.RAG: primary.id},
        fallbacks={primary.id: fallback.id},
    ))
    calls = []

    def fake_call(active_route):
        calls.append(active_route.id)
        raise error

    with pytest.raises(type(error)):
        gateway.invoke(request(), usage_group_id="g", call=fake_call)
    assert calls == ["primary"]
    assert classify_model_failure(error) is kind


def test_selection_validates_capability_permission_and_quota() -> None:
    admin_route = route(
        "admin-vision",
        capabilities={ModelCapability.VISION},
        minimum_role="admin",
    )
    policy = StaticModelRoutePolicy(
        (admin_route,), defaults={ModelSurface.RAG: admin_route.id}
    )
    with pytest.raises(ModelSelectionError, match="能力"):
        policy.resolve(request(user_role="admin"))
    with pytest.raises(ModelSelectionError, match="无权"):
        policy.resolve(request(
            required_capabilities=frozenset({ModelCapability.VISION}),
            user_role="user",
        ))
    with pytest.raises(ModelQuotaRejectedError):
        policy.resolve(request(
            required_capabilities=frozenset({ModelCapability.VISION}),
            user_role="admin",
            quota_allowed=False,
        ))


def test_every_model_surface_has_an_explicit_accounting_contract() -> None:
    contracts = {item["surface"]: item for item in accounting_contracts()}
    assert set(contracts) == {
        "rag", "agent", "vision_rag", "vision_agent", "vision_ocr",
        "rerank", "memory", "knowledge",
    }
    assert contracts["rerank"]["ledger_surface"] == "rerank"
    assert contracts["memory"]["quota_mode"] == "system_cost_nonbillable"


def test_quota_settle_release_unknown_and_shadow_to_enforce(tmp_path) -> None:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'quota.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(QuotaPlan(
            code="free", name="free", period_type="monthly",
            token_limit=1_000_000, request_limit=500,
        ))
        session.commit()
        shadow = QuotaApplicationService(session, policy_mode=QuotaPolicyMode.SHADOW)
        actual = shadow.reserve("u", "rag", "actual", 100, "group-a")
        shadow.settle(actual.id, ModelUsage.actual(20, 5))
        unknown = shadow.reserve("u", "agent", "unknown", 80, "group-b")
        shadow.settle(unknown.id, ModelUsage.unknown())
        released = shadow.reserve("u", "vision_rag", "released", 60, "group-c")
        shadow.release(released.id)
        current = shadow.current("u")
        assert current["used_tokens"] == 105
        assert current["reserved_tokens"] == 0
        assert current["token_limit"] == 1_000_000
        enforce = QuotaApplicationService(session, policy_mode=QuotaPolicyMode.ENFORCE)
        period = enforce.ensure_period("u")
        period.used_tokens = period.token_limit
        session.commit()
        with pytest.raises(QuotaExceededError):
            enforce.reserve("u", "rag", "blocked", 1, "group-d")
    engine.dispose()


def test_concurrent_reservations_do_not_overspend(tmp_path) -> None:
    database = tmp_path / "concurrent.db"
    engine = build_engine(f"sqlite+pysqlite:///{database}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", email="u@example.com", password_hash="x"))
        session.add(QuotaPlan(
            code="free", name="free", period_type="monthly",
            token_limit=100, request_limit=10,
        ))
        session.commit()
        QuotaApplicationService(
            session, policy_mode=QuotaPolicyMode.ENFORCE
        ).ensure_period("u")
    barrier = Barrier(2)

    def reserve(key: str) -> bool:
        with Session(engine, expire_on_commit=False) as session:
            service = QuotaApplicationService(session, policy_mode=QuotaPolicyMode.ENFORCE)
            barrier.wait(timeout=5)
            try:
                service.reserve("u", "rag", key, 80, key)
                return True
            except (QuotaExceededError, OperationalError):
                session.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("one", "two")))
    with Session(engine) as session:
        rows = session.query(QuotaReservation).filter_by(status="reserved").all()
        assert sum(row.reserved_tokens for row in rows) <= 100
        assert sum(results) <= 1
    engine.dispose()
