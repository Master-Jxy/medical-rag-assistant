"""本地依赖readiness探针；不初始化模型或访问外部供应商。"""

import os
from math import ceil
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from app.infrastructure.redis import RedisHealthStatus, RedisInfrastructure
from app.ports.readiness import ReadinessProbeResult


class DatabaseReadinessProbe:
    def __init__(self, database_url: str, timeout_seconds: float) -> None:
        url = make_url(database_url)
        connect_args: dict[str, object] = {}
        if url.get_backend_name() == "mysql":
            timeout = max(1, ceil(timeout_seconds))
            connect_args = {
                "connect_timeout": timeout,
                "read_timeout": timeout,
                "write_timeout": timeout,
            }
        elif url.get_backend_name() == "sqlite":
            connect_args = {"check_same_thread": False, "timeout": timeout_seconds}
        self._engine: Engine = create_engine(
            database_url,
            poolclass=NullPool,
            connect_args=connect_args,
        )

    def check(self) -> ReadinessProbeResult:
        try:
            with self._engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return ReadinessProbeResult(ok=True)
        except Exception:
            return ReadinessProbeResult(ok=False, failure_code="MYSQL_UNAVAILABLE")

    def close(self) -> None:
        self._engine.dispose()


class RedisReadinessProbe:
    def __init__(self, redis: RedisInfrastructure) -> None:
        self._redis = redis

    def check(self) -> ReadinessProbeResult:
        try:
            status = self._redis.health_status()
        except Exception:
            return ReadinessProbeResult(ok=False, failure_code="REDIS_UNAVAILABLE")
        if status is RedisHealthStatus.OK:
            return ReadinessProbeResult(ok=True)
        code = "REDIS_DISABLED" if status is RedisHealthStatus.DISABLED else "REDIS_UNAVAILABLE"
        return ReadinessProbeResult(ok=False, failure_code=code)

    def close(self) -> None:
        return None


class WritableDirectoryReadinessProbe:
    def __init__(self, path: Path, failure_code: str) -> None:
        self._path = path
        self._failure_code = failure_code

    def check(self) -> ReadinessProbeResult:
        try:
            ready = self._path.is_dir() and os.access(
                self._path,
                os.R_OK | os.W_OK | os.X_OK,
            )
        except OSError:
            ready = False
        return ReadinessProbeResult(
            ok=ready,
            failure_code=None if ready else self._failure_code,
        )

    def close(self) -> None:
        return None


class FailedReadinessProbe:
    def __init__(self, failure_code: str) -> None:
        self._failure_code = failure_code

    def check(self) -> ReadinessProbeResult:
        return ReadinessProbeResult(ok=False, failure_code=self._failure_code)

    def close(self) -> None:
        return None
