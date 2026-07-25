"""管理员可见的只读聚合统计契约。"""

from datetime import datetime

from pydantic import BaseModel


class TelemetryStatsResponse(BaseModel):
    generated_at: datetime
    request_total: int
    request_success: int
    request_failure: int
    success_rate: float | None
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
