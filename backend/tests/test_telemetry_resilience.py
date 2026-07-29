import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import RagServiceError
from app.infrastructure.redis import RedisHealthStatus
from app.infrastructure.telemetry import (
    LocalTelemetryAdapter,
    RotatingJsonFileTelemetryAdapter,
    create_local_telemetry,
)
from app.modules.rag.ports import GeneratedAnswerChunk, RetrievedChunk
from app.ports.telemetry import NullTelemetry, TelemetryEvent
from app.services.rag_service import RagService
from app.main import create_app


class StubRedisInfrastructure:
    def health_status(self) -> RedisHealthStatus:
        return RedisHealthStatus.DISABLED

    def close(self) -> None:
        return None


class Query:
    def build(self, question, history):
        return "query"


class Search:
    def search(self, query, top_k, options=None):
        return [RetrievedChunk("知识内容", "资料.txt", 1)]


class Answer:
    def answer(self, question, history, chunks):
        return "回答"

    def stream_answer(self, question, history, chunks):
        yield GeneratedAnswerChunk("回答")

    async def astream_answer(self, question, history, chunks):
        yield GeneratedAnswerChunk("回答")


class TimeoutAnswer(Answer):
    def answer(self, question, history, chunks):
        raise TimeoutError("model timeout")


def telemetry_event(index: int) -> TelemetryEvent:
    return TelemetryEvent.create(
        request_id=f"request-{index}",
        event_name="http_request",
        result="success",
        route="/api/v1/health",
        status_code=200,
        duration_ms=1.0,
    )


def test_rotating_json_log_obeys_size_and_backup_limits(tmp_path) -> None:
    log_path = tmp_path / "telemetry.jsonl"
    adapter = RotatingJsonFileTelemetryAdapter(
        log_path,
        max_bytes=512,
        backup_count=2,
    )
    for index in range(40):
        adapter.emit(telemetry_event(index))
    adapter.close()

    files = sorted(tmp_path.glob("telemetry.jsonl*"))
    assert 1 <= len(files) <= 3
    assert sum(path.stat().st_size for path in files) <= 3 * 512
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert json.loads(line)["event_name"] == "http_request"


def test_http_telemetry_excludes_query_headers_and_business_body(tmp_path) -> None:
    log_path = tmp_path / "telemetry.jsonl"
    settings = Settings(
        _env_file=None,
        telemetry_log_path=log_path,
        telemetry_log_max_bytes=4096,
        telemetry_log_backup_count=1,
    )
    application = create_app(
        redis_infrastructure=StubRedisInfrastructure(),
        settings=settings,
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/missing?password=query-secret",
            headers={"Authorization": "Bearer bearer-secret"},
            json={"question": "medical-body-secret"},
        )

    assert response.status_code == 404
    log_text = log_path.read_text(encoding="utf-8")
    assert "query-secret" not in log_text
    assert "bearer-secret" not in log_text
    assert "medical-body-secret" not in log_text
    assert json.loads(log_text.splitlines()[-1])["route"] == "/api/v1/missing"


def test_model_timeout_is_counted_without_changing_rag_error_contract() -> None:
    telemetry = LocalTelemetryAdapter()
    service = RagService(Query(), Search(), TimeoutAnswer(), telemetry=telemetry)

    with pytest.raises(RagServiceError):
        service.ask("问题", 4)

    snapshot = telemetry.snapshot()
    assert snapshot.failure_counts["model"] == 1
    assert snapshot.error_type_counts["TimeoutError"] == 1
    assert snapshot.token_measurement == "unknown"
    assert snapshot.estimated_cost_cny is None


def test_disabled_telemetry_keeps_business_flow_available(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        telemetry_enabled=False,
        telemetry_log_path=tmp_path / "must-not-exist.jsonl",
    )
    telemetry = create_local_telemetry(settings)
    service = RagService(Query(), Search(), Answer(), telemetry=telemetry)

    assert isinstance(telemetry, NullTelemetry)
    assert service.ask("问题", 4)[0] == "回答"
    assert telemetry.snapshot().request_total == 0
    assert not settings.telemetry_log_path.exists()
