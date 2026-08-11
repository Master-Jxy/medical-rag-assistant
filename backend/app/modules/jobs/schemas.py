"""任务中心安全响应契约。"""

from datetime import datetime

from pydantic import BaseModel


class JobItem(BaseModel):
    job_id: str
    job_type: str
    object_type: str
    object_id: str
    dispatch_key: str
    status: str
    progress: int
    attempt_count: int
    max_attempts: int
    error_type: str | None
    last_error_code: str | None
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobListResponse(BaseModel):
    items: list[JobItem]
    total: int
    offset: int
    limit: int
