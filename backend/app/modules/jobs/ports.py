"""业务模块维护处理任务时依赖的小型契约。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class JobReference:
    id: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class JobLease:
    id: str
    job_type: str
    object_type: str
    object_id: str
    payload: dict
    attempt_count: int
    max_attempts: int
    lease_owner: str


class JobPort(Protocol):
    def enqueue(
        self,
        *,
        dispatch_key: str,
        job_type: str,
        object_type: str,
        object_id: str,
        payload: dict | None = None,
        max_attempts: int = 3,
    ) -> JobReference: ...

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

    def complete_running_for_object(
        self,
        *,
        job_type: str,
        object_type: str,
        object_id: str,
    ) -> int: ...
