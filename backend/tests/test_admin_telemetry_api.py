from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.infrastructure.redis import RedisHealthStatus
from app.infrastructure.telemetry import LocalTelemetryAdapter
from app.main import create_app
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.ports.telemetry import TelemetryEvent


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


def test_admin_stats_are_aggregated_and_normal_user_gets_stable_403() -> None:
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
    assert body["estimated_cost_cny"] is None
    assert "question" not in body
    assert "answer" not in body
