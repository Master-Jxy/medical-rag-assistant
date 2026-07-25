"""业务模块维护处理任务时依赖的小型契约。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class JobReference:
    id: str
    attempt_count: int


class JobPort(Protocol):
    def start(
        self,
        *,
        job_type: str,
        object_type: str,
        object_id: str,
        initial_progress: int,
    ) -> JobReference: ...

    def complete(self, job_id: str) -> None: ...

    def fail(self, job_id: str, error_type: str) -> None: ...
