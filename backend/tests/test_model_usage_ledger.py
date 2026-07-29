from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.modules.rag.ports import ModelUsage
from app.modules.usage.models import ModelUsageRecord
from app.modules.usage.service import ModelUsageRecorder


def build_recorder(tmp_path, **settings) -> tuple[Session, ModelUsageRecorder]:
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'usage.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    return session, ModelUsageRecorder(
        session,
        Settings(_env_file=None, **settings),
    )


def test_usage_ledger_is_idempotent_and_snapshots_price(tmp_path) -> None:
    session, recorder = build_recorder(
        tmp_path,
        chat_input_price_per_million_tokens_cny=2.5,
        chat_output_price_per_million_tokens_cny=10,
    )

    first = recorder.record(
        call_id="rag:message-1:answer",
        request_id="request-1",
        user_id=None,
        surface="rag",
        operation="answer",
        model_name="fake-chat",
        usage=ModelUsage.actual(100, 20),
    )
    second = recorder.record(
        call_id="rag:message-1:answer",
        request_id="request-2",
        user_id=None,
        surface="rag",
        operation="answer",
        model_name="different",
        usage=ModelUsage.actual(999, 999),
    )

    assert first.id == second.id
    assert session.query(ModelUsageRecord).count() == 1
    assert first.input_price_snapshot == Decimal("2.50000000")
    assert first.output_price_snapshot == Decimal("10.00000000")
    assert first.estimated_cost_cny == Decimal("0.00045000")
    session.close()


def test_usage_aggregate_preserves_known_values_and_reports_coverage(tmp_path) -> None:
    session, recorder = build_recorder(tmp_path)
    common = {
        "request_id": None,
        "user_id": None,
        "surface": "rag",
        "operation": "answer",
        "model_name": "fake-chat",
    }
    recorder.record(call_id="actual", usage=ModelUsage.actual(30, 7), **common)
    recorder.record(call_id="unknown", usage=ModelUsage.unknown(), **common)
    recorder.record(
        call_id="no-model",
        usage=ModelUsage.not_applicable(),
        **common,
    )

    aggregate = recorder.aggregate()

    assert aggregate.input_tokens == 30
    assert aggregate.output_tokens == 7
    assert aggregate.known_model_calls == 1
    assert aggregate.unknown_model_calls == 1
    assert aggregate.no_model_calls == 1
    assert aggregate.priced_model_calls == 0
    assert aggregate.unpriced_model_calls == 1
    assert aggregate.measurement_coverage == 0.5
    assert aggregate.estimated_cost_cny == 0
    session.close()


def test_zero_model_call_is_zero_cost_and_unknown_never_uses_character_estimate(
    tmp_path,
) -> None:
    session, recorder = build_recorder(
        tmp_path,
        chat_input_price_per_million_tokens_cny=2.5,
        chat_output_price_per_million_tokens_cny=10,
    )
    common = {
        "request_id": None,
        "user_id": None,
        "surface": "rag",
        "operation": "answer",
        "model_name": "fake-chat",
    }
    zero = recorder.record(
        call_id="zero",
        usage=ModelUsage.not_applicable(),
        **common,
    )
    unknown = recorder.record(
        call_id="unknown",
        usage=ModelUsage.unknown(),
        **common,
    )

    assert zero.input_tokens == zero.output_tokens == zero.total_tokens == 0
    assert zero.estimated_cost_cny == 0
    assert unknown.input_tokens is None
    assert unknown.output_tokens is None
    assert unknown.estimated_cost_cny is None
    session.close()
