import json

from fastapi.testclient import TestClient

from app.infrastructure.redis import RedisHealthStatus
from app.infrastructure.telemetry import JsonLoggingTelemetryAdapter
from app.main import create_app


class DisabledRedis:
    def health_status(self):
        return RedisHealthStatus.DISABLED

    def close(self):
        pass


class RecordingTelemetry:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)


def test_http_request_uses_same_request_id_for_success_and_error() -> None:
    telemetry = RecordingTelemetry()
    application = create_app(
        redis_infrastructure=DisabledRedis(),
        telemetry=telemetry,
    )

    with TestClient(application) as client:
        success = client.get("/api/v1/health")
        failure = client.post(
            "/api/v1/chat",
            json={"question": "不会调用模型", "top_k": 2},
        )

    assert success.status_code == 200
    assert failure.status_code == 401
    assert failure.headers["x-request-id"] == failure.json()["request_id"]
    http_events = [
        event for event in telemetry.events if event.event_name == "http_request"
    ]
    assert [event.event_name for event in http_events] == [
        "http_request",
        "http_request",
    ]
    assert http_events[0].request_id == success.headers["x-request-id"]
    assert http_events[1].request_id == failure.headers["x-request-id"]
    assert http_events[1].result == "failure"
    error_event = next(
        event for event in telemetry.events if event.event_name == "application_error"
    )
    assert error_event.request_id == failure.headers["x-request-id"]


def test_json_adapter_serializes_only_fixed_safe_fields(caplog) -> None:
    from app.ports.telemetry import TelemetryEvent

    caplog.set_level("INFO", logger="medical_rag.telemetry")
    JsonLoggingTelemetryAdapter().emit(
        TelemetryEvent.create(
            request_id="request-1",
            event_name="http_request",
            result="success",
            route="/api/v1/health",
            status_code=200,
        )
    )

    payload = json.loads(caplog.records[-1].message)
    assert payload["request_id"] == "request-1"
    assert payload["event_name"] == "http_request"
    assert set(payload) <= {
        "request_id",
        "event_name",
        "result",
        "timestamp",
        "route",
        "user_id",
        "status_code",
        "error_type",
        "stage",
        "duration_ms",
        "model_name",
        "input_tokens",
        "output_tokens",
        "token_measurement",
        "estimated_cost_cny",
        "retrieved_chunk_count",
    }
