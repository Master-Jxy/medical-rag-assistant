"""管理员统计用例：只读取Telemetry聚合快照。"""

from datetime import datetime, timezone

from app.ports.telemetry import TelemetryMetricsPort
from app.schemas.telemetry import TelemetryStatsResponse
from app.modules.usage.service import ModelUsageRecorder
from sqlalchemy.orm import Session


class TelemetryStatsService:
    def __init__(self, telemetry: TelemetryMetricsPort, session: Session) -> None:
        self.telemetry = telemetry
        self.usage = ModelUsageRecorder(session)

    def get_stats(self) -> TelemetryStatsResponse:
        snapshot = self.telemetry.snapshot()
        usage = self.usage.aggregate()
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
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            token_measurement=(
                "unknown" if usage.unknown_model_calls else "measured"
            ),
            estimated_cost_cny=float(usage.estimated_cost_cny),
            known_model_calls=usage.known_model_calls,
            unknown_model_calls=usage.unknown_model_calls,
            no_model_calls=usage.no_model_calls,
            priced_model_calls=usage.priced_model_calls,
            unpriced_model_calls=usage.unpriced_model_calls,
            measurement_coverage=usage.measurement_coverage,
            rate_limit_count=snapshot.rate_limit_count,
            redis_degradation_count=snapshot.redis_degradation_count,
            user_stop_count=snapshot.user_stop_count,
            failure_counts=snapshot.failure_counts,
            error_type_counts=top_errors,
        )
