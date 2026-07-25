"""管理员统计用例：只读取Telemetry聚合快照。"""

from datetime import datetime, timezone

from app.ports.telemetry import TelemetryMetricsPort
from app.schemas.telemetry import TelemetryStatsResponse


class TelemetryStatsService:
    def __init__(self, telemetry: TelemetryMetricsPort) -> None:
        self.telemetry = telemetry

    def get_stats(self) -> TelemetryStatsResponse:
        snapshot = self.telemetry.snapshot()
        success_rate = (
            round(snapshot.request_success / snapshot.request_total, 6)
            if snapshot.request_total
            else None
        )
        top_errors = dict(
            sorted(
                snapshot.error_type_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        )
        return TelemetryStatsResponse(
            generated_at=datetime.now(timezone.utc),
            request_total=snapshot.request_total,
            request_success=snapshot.request_success,
            request_failure=snapshot.request_failure,
            success_rate=success_rate,
            average_duration_ms=snapshot.average_duration_ms,
            stage_average_duration_ms=snapshot.stage_average_duration_ms,
            input_tokens=snapshot.input_tokens,
            output_tokens=snapshot.output_tokens,
            token_measurement=snapshot.token_measurement,
            estimated_cost_cny=snapshot.estimated_cost_cny,
            rate_limit_count=snapshot.rate_limit_count,
            redis_degradation_count=snapshot.redis_degradation_count,
            user_stop_count=snapshot.user_stop_count,
            failure_counts=snapshot.failure_counts,
            error_type_counts=top_errors,
        )
