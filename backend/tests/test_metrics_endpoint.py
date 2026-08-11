from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.infrastructure.telemetry import LocalTelemetryAdapter
from app.main import create_app
from app.ports.telemetry import TelemetryEvent


def test_metrics_is_disabled_by_default_and_token_protected() -> None:
    telemetry = LocalTelemetryAdapter()
    telemetry.emit(
        TelemetryEvent.create(
            request_id="request-not-exported",
            event_name="http_request",
            result="success",
            route="/private",
            user_id="user-not-exported",
            status_code=200,
            duration_ms=4,
        )
    )
    application = create_app(telemetry=telemetry)
    settings = Settings(_env_file=None, metrics_enabled=False)
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        assert client.get("/metrics").status_code == 404
    application.dependency_overrides.clear()


def test_metrics_contains_only_bounded_fields_when_enabled() -> None:
    telemetry = LocalTelemetryAdapter()
    telemetry.emit(
        TelemetryEvent.create(
            request_id="request-not-exported",
            event_name="http_request",
            result="success",
            route="/private",
            user_id="user-not-exported",
            status_code=200,
            duration_ms=4,
        )
    )
    application = create_app(telemetry=telemetry)
    settings = Settings(
        _env_file=None,
        metrics_enabled=True,
        metrics_bearer_token="test-metrics-token",
    )
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        assert client.get("/metrics").status_code == 401
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer test-metrics-token"},
        )
    application.dependency_overrides.clear()
    assert response.status_code == 200
    assert "medical_rag_http_requests_total" in response.text
    assert "user-not-exported" not in response.text
    assert "request-not-exported" not in response.text
    assert "route" not in response.text
