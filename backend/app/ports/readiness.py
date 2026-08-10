"""Readiness依赖探针Port，隔离应用编排与具体基础设施。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReadinessProbeResult:
    ok: bool
    failure_code: str | None = None


class ReadinessProbe(Protocol):
    def check(self) -> ReadinessProbeResult: ...

    def close(self) -> None: ...
