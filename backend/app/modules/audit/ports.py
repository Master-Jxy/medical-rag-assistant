"""业务模块写安全审计时依赖的小型契约。"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AuditRecord:
    actor_user_id: str
    action: str
    object_type: str
    object_id: str
    result: str = "success"
    request_id: str | None = None
    details: dict[str, str | bool | int | None] = field(default_factory=dict)


class AuditPort(Protocol):
    def record(self, event: AuditRecord) -> None: ...
