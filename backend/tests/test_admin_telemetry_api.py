from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, get_db_session
from app.infrastructure.redis import RedisHealthStatus
from app.infrastructure.telemetry import LocalTelemetryAdapter
from app.main import create_app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.ports.telemetry import TelemetryEvent
from app.modules.rag.ports import ModelUsage
from app.modules.usage.service import ModelUsageRecorder


class DisabledRedis:
    def health_status(self):
        return RedisHealthStatus.DISABLED

    def close(self):
        pass


def user(role: str) -> UserResponse:
    now = datetime.now(timezone.utc)
    return UserResponse(
        id=f"{role}-1",
        email=f"{role}@example.com",
        display_name=role,
        is_active=True,
        role=role,
        created_at=now,
        updated_at=now,
    )


def test_admin_stats_are_aggregated_and_normal_user_gets_stable_403(tmp_path) -> None:
    telemetry = LocalTelemetryAdapter()
    telemetry.emit(
        TelemetryEvent.create(
            request_id="seed",
            event_name="http_request",
            result="success",
            route="/seed",
            status_code=200,
            duration_ms=12,
        )
    )
    application = create_app(
        redis_infrastructure=DisabledRedis(),
        telemetry=telemetry,
    )
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'telemetry.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        recorder = ModelUsageRecorder(
            session,
            Settings(
                _env_file=None,
                chat_input_price_per_million_tokens_cny=2,
                chat_output_price_per_million_tokens_cny=8,
            ),
        )
        recorder.record(
            call_id="known",
            request_id=None,
            user_id=None,
            surface="rag",
            operation="answer",
            model_name="fake",
            usage=ModelUsage.actual(100, 25),
        )
        recorder.record(
            call_id="unknown",
            request_id=None,
            user_id=None,
            surface="rag",
            operation="answer",
            model_name="fake",
            usage=ModelUsage.unknown(),
        )

    def override_session():
        with factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_session
    application.dependency_overrides[get_current_user] = lambda: user("user")
    with TestClient(application) as client:
        forbidden = client.get("/api/v1/admin/telemetry/stats")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ADMIN_REQUIRED"

    application.dependency_overrides[get_current_user] = lambda: user("admin")
    with TestClient(application) as client:
        allowed = client.get("/api/v1/admin/telemetry/stats")
    application.dependency_overrides.clear()

    assert allowed.status_code == 200
    body = allowed.json()
    assert body["request_total"] >= 2
    assert 0 <= body["success_rate"] <= 1
    assert body["stage_average_duration_ms"]["tool"] is None
    assert body["token_measurement"] == "unknown"
    assert body["input_tokens"] == 100
    assert body["output_tokens"] == 25
    assert body["known_model_calls"] == 1
    assert body["unknown_model_calls"] == 1
    assert body["measurement_coverage"] == 0.5
    assert body["estimated_cost_cny"] == 0.0004
    assert "question" not in body
    assert "answer" not in body
