"""轻量可观测性 Port；业务层不依赖具体日志或指标平台。"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class TelemetryEvent:
    request_id: str
    event_name: str
    result: str
    timestamp: str
    route: str | None = None
    user_id: str | None = None
    status_code: int | None = None
    error_type: str | None = None
    stage: str | None = None
    duration_ms: float | None = None
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    token_measurement: str | None = None
    estimated_cost_cny: float | None = None
    retrieved_chunk_count: int | None = None

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        event_name: str,
        result: str,
        **fields,
    ) -> "TelemetryEvent":
        return cls(
            request_id=request_id,
            event_name=event_name,
            result=result,
            timestamp=datetime.now(timezone.utc).isoformat(),
            **fields,
        )

    def as_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class TelemetryPort(Protocol):
    def emit(self, event: TelemetryEvent) -> None:
        """提交一个不含业务正文的观测事件。"""


@dataclass(frozen=True)
class TelemetryMetricsSnapshot:
    request_total: int
    request_success: int
    request_failure: int
    average_duration_ms: float | None
    stage_average_duration_ms: dict[str, float | None]
    input_tokens: int
    output_tokens: int
    token_measurement: str
    estimated_cost_cny: float | None
    rate_limit_count: int
    redis_degradation_count: int
    user_stop_count: int
    failure_counts: dict[str, int]
    error_type_counts: dict[str, int]
    request_p50_duration_ms: float | None = None
    request_p95_duration_ms: float | None = None
    stage_p95_duration_ms: dict[str, float | None] | None = None
    window_kind: str = "process_lifetime"
    process_started_at: str | None = None


class TelemetryMetricsPort(TelemetryPort, Protocol):
    def snapshot(self) -> TelemetryMetricsSnapshot:
        """返回不含日志正文的进程内聚合快照。"""


def render_prometheus(snapshot: TelemetryMetricsSnapshot) -> str:
    """Render bounded, low-cardinality process metrics."""

    lines = [
        "# TYPE medical_rag_http_requests_total counter",
        f'medical_rag_http_requests_total{{result="success"}} {snapshot.request_success}',
        f'medical_rag_http_requests_total{{result="failure"}} {snapshot.request_failure}',
        "# TYPE medical_rag_http_request_duration_ms gauge",
        f"medical_rag_http_request_duration_ms {snapshot.average_duration_ms or 0}",
        f"medical_rag_http_request_p50_duration_ms {snapshot.request_p50_duration_ms or 0}",
        f"medical_rag_http_request_p95_duration_ms {snapshot.request_p95_duration_ms or 0}",
        "# TYPE medical_rag_model_input_tokens_total counter",
        f"medical_rag_model_input_tokens_total {snapshot.input_tokens}",
        "# TYPE medical_rag_model_output_tokens_total counter",
        f"medical_rag_model_output_tokens_total {snapshot.output_tokens}",
        "# TYPE medical_rag_rate_limit_total counter",
        f"medical_rag_rate_limit_total {snapshot.rate_limit_count}",
        "# TYPE medical_rag_redis_degradation_total counter",
        f"medical_rag_redis_degradation_total {snapshot.redis_degradation_count}",
        "# TYPE medical_rag_user_stop_total counter",
        f"medical_rag_user_stop_total {snapshot.user_stop_count}",
    ]
    for stage, value in sorted(snapshot.stage_average_duration_ms.items()):
        safe_stage = stage.replace("-", "_")
        lines.append(
            f'medical_rag_stage_duration_ms{{stage="{safe_stage}"}} {value or 0}'
        )
    return "\n".join(lines) + "\n"


class NullTelemetry:
    def emit(self, event: TelemetryEvent) -> None:
        return None

    def snapshot(self) -> TelemetryMetricsSnapshot:
        return TelemetryMetricsSnapshot(
            request_total=0,
            request_success=0,
            request_failure=0,
            average_duration_ms=None,
            stage_average_duration_ms={
                stage: None
                for stage in (
                    "query_construction",
                    "knowledge_retrieval",
                    "rerank",
                    "model_generation",
                    "tool",
                )
            },
            input_tokens=0,
            output_tokens=0,
            token_measurement="unknown",
            estimated_cost_cny=None,
            rate_limit_count=0,
            redis_degradation_count=0,
            user_stop_count=0,
            failure_counts={"model": 0, "retrieval": 0, "persistence": 0},
            error_type_counts={},
            request_p50_duration_ms=None,
            request_p95_duration_ms=None,
            stage_p95_duration_ms={
                stage: None
                for stage in (
                    "query_construction",
                    "knowledge_retrieval",
                    "rerank",
                    "model_generation",
                    "tool",
                )
            },
            window_kind="process_lifetime",
            process_started_at=None,
        )


def emit_safely(telemetry: TelemetryPort, event: TelemetryEvent) -> None:
    """可观测性永远旁路失败，不能改变业务结果。"""
    try:
        telemetry.emit(event)
    except Exception:
        return None
