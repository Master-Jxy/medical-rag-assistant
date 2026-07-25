"""审计中心安全响应契约。"""

from datetime import datetime

from pydantic import BaseModel


class AuditEventItem(BaseModel):
    event_id: str
    actor_user_id: str
    action: str
    object_type: str
    object_id: str
    result: str
    request_id: str | None
    details: dict[str, str | bool | int | None]
    created_at: datetime


class AuditEventListResponse(BaseModel):
    items: list[AuditEventItem]
    total: int
    offset: int
    limit: int
