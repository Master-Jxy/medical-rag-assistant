"""默认JSON日志适配器；只序列化TelemetryEvent固定字段。"""

import json
import logging
from logging.handlers import RotatingFileHandler
from collections import Counter, defaultdict
from pathlib import Path
from threading import Lock

from app.core.config import Settings
from app.ports.telemetry import TelemetryEvent, TelemetryMetricsSnapshot

logger = logging.getLogger("medical_rag.telemetry")


class JsonLoggingTelemetryAdapter:
    def emit(self, event: TelemetryEvent) -> None:
        # Alembic 等日志配置可能禁用既有 logger；显式适配器应保持可用。
        logger.disabled = False
        logger.info(
            json.dumps(
                event.as_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )


class RotatingJsonFileTelemetryAdapter:
    """写入有大小上限的JSONL文件；只接收固定字段事件。"""

    def __init__(self, path: Path, *, max_bytes: int, backup_count: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, event: TelemetryEvent) -> None:
        record = logging.LogRecord(
            name="medical_rag.telemetry.file",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=json.dumps(
                event.as_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            args=(),
            exc_info=None,
        )
        self._handler.handle(record)

    def close(self) -> None:
        self._handler.close()


class InMemoryTelemetryMetrics:
    """进程内聚合；Redis不是指标真相源，进程重启后从零开始。"""

    STAGES = (
        "query_construction",
        "knowledge_retrieval",
        "rerank",
        "model_generation",
        "tool",
    )

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_total = 0
        self._request_success = 0
        self._request_failure = 0
        self._request_duration_total = 0.0
        self._request_duration_count = 0
        self._stage_duration_total: dict[str, float] = defaultdict(float)
        self._stage_duration_count: Counter[str] = Counter()
        self._input_tokens = 0
        self._output_tokens = 0
        self._known_token_events = 0
        self._unknown_token_events = 0
        self._estimated_cost_total = 0.0
        self._known_cost_events = 0
        self._unknown_cost_events = 0
        self._rate_limit_count = 0
        self._redis_degradation_count = 0
        self._user_stop_count = 0
        self._failure_counts: Counter[str] = Counter()
        self._error_type_counts: Counter[str] = Counter()

    def emit(self, event: TelemetryEvent) -> None:
        with self._lock:
            if event.event_name == "http_request":
                self._request_total += 1
                if event.result == "success":
                    self._request_success += 1
                else:
                    self._request_failure += 1
                if event.status_code == 429:
                    self._rate_limit_count += 1
                if event.duration_ms is not None:
                    self._request_duration_total += event.duration_ms
                    self._request_duration_count += 1

            if event.event_name == "rag_stage" and event.stage:
                if event.duration_ms is not None:
                    self._stage_duration_total[event.stage] += event.duration_ms
                    self._stage_duration_count[event.stage] += 1
                if event.result == "failure":
                    failure_key = {
                        "knowledge_retrieval": "retrieval",
                        "model_generation": "model",
                    }.get(event.stage)
                    if failure_key:
                        self._failure_counts[failure_key] += 1

            if event.event_name == "redis_degraded":
                self._redis_degradation_count += 1
            elif event.event_name == "generation_stopped" and event.result == "success":
                self._user_stop_count += 1
            elif event.event_name == "persistence_failure":
                self._failure_counts["persistence"] += 1

            if event.error_type:
                self._error_type_counts[event.error_type] += 1

            if event.event_name == "rag_stage" and event.stage == "model_generation":
                if (
                    event.token_measurement in {"actual", "estimated"}
                    and event.input_tokens is not None
                    and event.output_tokens is not None
                ):
                    self._input_tokens += event.input_tokens
                    self._output_tokens += event.output_tokens
                    self._known_token_events += 1
                else:
                    self._unknown_token_events += 1
                if event.estimated_cost_cny is None:
                    self._unknown_cost_events += 1
                else:
                    self._estimated_cost_total += event.estimated_cost_cny
                    self._known_cost_events += 1

    def snapshot(self) -> TelemetryMetricsSnapshot:
        with self._lock:
            stage_averages = {
                stage: (
                    round(
                        self._stage_duration_total[stage]
                        / self._stage_duration_count[stage],
                        3,
                    )
                    if self._stage_duration_count[stage]
                    else None
                )
                for stage in self.STAGES
            }
            if self._unknown_token_events:
                token_measurement = "unknown"
            elif self._known_token_events:
                token_measurement = "measured"
            else:
                token_measurement = "unknown"
            estimated_cost = (
                round(self._estimated_cost_total, 6)
                if self._known_cost_events and not self._unknown_cost_events
                else None
            )
            return TelemetryMetricsSnapshot(
                request_total=self._request_total,
                request_success=self._request_success,
                request_failure=self._request_failure,
                average_duration_ms=(
                    round(
                        self._request_duration_total / self._request_duration_count,
                        3,
                    )
                    if self._request_duration_count
                    else None
                ),
                stage_average_duration_ms=stage_averages,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                token_measurement=token_measurement,
                estimated_cost_cny=estimated_cost,
                rate_limit_count=self._rate_limit_count,
                redis_degradation_count=self._redis_degradation_count,
                user_stop_count=self._user_stop_count,
                failure_counts={
                    key: self._failure_counts[key]
                    for key in ("model", "retrieval", "persistence")
                },
                error_type_counts=dict(self._error_type_counts),
            )


class LocalTelemetryAdapter:
    """默认轻量实现：JSON日志与内存指标彼此隔离。"""

    def __init__(
        self,
        logger_adapter: object | None = None,
        metrics: InMemoryTelemetryMetrics | None = None,
    ) -> None:
        self.logger_adapter = logger_adapter or JsonLoggingTelemetryAdapter()
        self.metrics = metrics or InMemoryTelemetryMetrics()

    def emit(self, event: TelemetryEvent) -> None:
        try:
            self.logger_adapter.emit(event)
        except Exception:
            pass
        try:
            self.metrics.emit(event)
        except Exception:
            pass

    def snapshot(self) -> TelemetryMetricsSnapshot:
        return self.metrics.snapshot()

    def close(self) -> None:
        close = getattr(self.logger_adapter, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def create_local_telemetry(settings: Settings):
    """按配置创建默认旁路实现；关闭时返回空实现。"""
    if not settings.telemetry_enabled:
        from app.ports.telemetry import NullTelemetry

        return NullTelemetry()
    return LocalTelemetryAdapter(
        logger_adapter=RotatingJsonFileTelemetryAdapter(
            settings.telemetry_log_path,
            max_bytes=settings.telemetry_log_max_bytes,
            backup_count=settings.telemetry_log_backup_count,
        )
    )
