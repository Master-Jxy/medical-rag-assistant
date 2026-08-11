from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import User
from app.modules.usage.contracts import QuotaPolicyMode
from app.modules.usage.models import QuotaPlan, QuotaPolicyEvent, QuotaReservation
from app.modules.usage.quota_service import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    QuotaApplicationService,
    normalize_idempotency_key,
)
from app.modules.vision.service import build_vision_quota_key


def test_vision_quota_keys_are_bounded_stable_and_scope_sensitive() -> None:
    identity = (
        "user-" + "u" * 80,
        "asset-" + "a" * 80,
        "scope-" + "s" * 80,
    )

    overview = build_vision_quota_key("overview", *identity, "overview")
    overview_replay = build_vision_quota_key("overview", *identity, "overview")
    different_scope = build_vision_quota_key(
        "overview", identity[0], identity[1], identity[2] + "-other", "overview"
    )
    focused = build_vision_quota_key("focused", *identity, "focus-hash")
    different_focus = build_vision_quota_key(
        "focused", *identity, "different-focus-hash"
    )
    report = build_vision_quota_key("report_extract", *identity, "ocr:v1")

    assert overview == overview_replay
    assert overview != different_scope
    assert focused != different_focus
    assert overview.startswith("vision:overview:")
    assert focused.startswith("vision:focused:")
    assert report.startswith("vision:report_extract:")
    assert all(
        len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH
        for key in (overview, different_scope, focused, different_focus, report)
    )


def test_quota_service_normalizes_long_keys_before_persistence() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(User(id="quota-key-user", email="quota-key@example.com", password_hash="x"))
    session.add(
        QuotaPlan(
            code="free",
            name="free",
            period_type="monthly",
            token_limit=1_000_000,
            request_limit=500,
        )
    )
    session.commit()
    try:
        long_key = "vision:report_extract:" + "composite-identity:" * 20
        normalized = normalize_idempotency_key(long_key)
        service = QuotaApplicationService(
            session,
            policy_mode=QuotaPolicyMode.SHADOW,
        )

        first = service.reserve(
            "quota-key-user",
            "vision_rag",
            long_key,
            100,
            "usage-group",
        )
        replay = service.reserve(
            "quota-key-user",
            "vision_rag",
            long_key,
            100,
            "usage-group",
        )

        reservation = session.query(QuotaReservation).one()
        event = session.query(QuotaPolicyEvent).one()
        assert first.id == replay.id == reservation.id
        assert reservation.idempotency_key == normalized
        assert event.idempotency_key == normalized
        assert normalized.startswith("vision:report_extract:")
        assert len(normalized) == IDEMPOTENCY_KEY_MAX_LENGTH
    finally:
        session.close()
        engine.dispose()


def test_generic_normalization_is_deterministic_and_collision_resistant() -> None:
    base = "surface:operation:" + "x" * 200
    first = normalize_idempotency_key(base + "a")
    replay = normalize_idempotency_key(base + "a")
    different = normalize_idempotency_key(base + "b")

    assert first == replay
    assert first != different
    assert len(first) == IDEMPOTENCY_KEY_MAX_LENGTH
    assert normalize_idempotency_key("short-key") == "short-key"
