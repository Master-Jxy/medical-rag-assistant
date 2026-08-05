"""Web snapshot contracts used by knowledge submission workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.exceptions import AppError


class WebSnapshotError(AppError):
    def __init__(
        self,
        message: str = "网页快照抓取失败，请检查地址后重试",
        *,
        code: str = "WEB_SNAPSHOT_FETCH_ERROR",
        status_code: int = 422,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)


class WebSnapshotDisabledError(WebSnapshotError):
    def __init__(self) -> None:
        super().__init__(
            "网页快照导入当前未启用",
            code="WEB_SNAPSHOT_DISABLED",
            status_code=503,
        )


class WebSnapshotTooLargeError(WebSnapshotError):
    def __init__(self) -> None:
        super().__init__(
            "网页响应内容超过限制",
            code="WEB_SNAPSHOT_TOO_LARGE",
            status_code=413,
        )


class WebSnapshotTimeoutError(WebSnapshotError):
    def __init__(self) -> None:
        super().__init__(
            "网页抓取超时",
            code="WEB_SNAPSHOT_TIMEOUT",
            status_code=504,
        )


@dataclass(frozen=True, slots=True)
class WebSnapshotResult:
    original_url: str
    final_url: str
    fetched_at: datetime
    mime_type: str
    content_sha256: str
    content: bytes


class WebSnapshotFetchPort(Protocol):
    async def fetch(self, url: str) -> WebSnapshotResult: ...
