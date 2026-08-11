"""脱敏的稳定性与数据清理检查契约。"""

from datetime import datetime

from pydantic import BaseModel


class SloChecksResponse(BaseModel):
    generated_at: datetime
    stale_job_count: int
    expired_quota_reservation_count: int
    orphan_media_count: int
    backup_status: str
    backup_age_hours: float | None
    overall_status: str
