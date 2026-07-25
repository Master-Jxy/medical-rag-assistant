from app.infrastructure.telemetry import InMemoryTelemetryMetrics, LocalTelemetryAdapter
from app.ports.telemetry import TelemetryEvent
from app.services.protection_observability import ProtectionObservability, RATE_LIMIT
from app.services.stream_cancellation_service import StreamCancellationService


def event(name, result="success", **fields):
    return TelemetryEvent.create(
        request_id="request-1",
        event_name=name,
        result=result,
        **fields,
    )


def test_metrics_aggregate_requests_stages_failures_and_unknown_usage() -> None:
    metrics = InMemoryTelemetryMetrics()
    metrics.emit(event("http_request", duration_ms=10, status_code=200))
    metrics.emit(event("http_request", "failure", duration_ms=30, status_code=429))
    metrics.emit(
        event(
            "rag_stage",
            stage="knowledge_retrieval",
            duration_ms=4,
            retrieved_chunk_count=4,
        )
    )
    metrics.emit(
        event(
            "rag_stage",
            "failure",
            stage="model_generation",
            duration_ms=6,
            error_type="TimeoutError",
            token_measurement="unknown",
        )
    )
    metrics.emit(event("persistence_failure", "failure", error_type="StoreError"))

    snapshot = metrics.snapshot()

    assert snapshot.request_total == 2
    assert snapshot.request_success == 1
    assert snapshot.request_failure == 1
    assert snapshot.average_duration_ms == 20
    assert snapshot.stage_average_duration_ms["knowledge_retrieval"] == 4
    assert snapshot.stage_average_duration_ms["tool"] is None
    assert snapshot.token_measurement == "unknown"
    assert snapshot.estimated_cost_cny is None
    assert snapshot.rate_limit_count == 1
    assert snapshot.failure_counts == {
        "model": 1,
        "retrieval": 0,
        "persistence": 1,
    }


def test_redis_degradation_and_user_stop_are_counted_without_redis_storage() -> None:
    telemetry = LocalTelemetryAdapter()
    protection = ProtectionObservability(
        redis_configured=True,
        telemetry=telemetry,
    )
    protection.record_failure(RATE_LIMIT, "RedisTimeout")
    cancellation = StreamCancellationService(telemetry)
    cancellation.register("user-1", "conversation-1", "key-1")

    assert cancellation.request_stop("user-1", "conversation-1", "key-1") is True
    snapshot = telemetry.snapshot()
    assert snapshot.redis_degradation_count == 1
    assert snapshot.user_stop_count == 1
    assert snapshot.error_type_counts["RedisTimeout"] == 1
