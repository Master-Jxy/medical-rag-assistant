"""应用健康状态用例，组合基础设施状态但不暴露连接信息。"""

from dataclasses import dataclass

from fastapi import Depends, Request

from app.infrastructure.redis import RedisHealthStatus, RedisInfrastructure
from app.infrastructure.readiness import (
    DatabaseReadinessProbe,
    FailedReadinessProbe,
    RedisReadinessProbe,
    WritableDirectoryReadinessProbe,
)
from app.core.config import Settings
from app.ports.readiness import ReadinessProbe
from app.services.protection_observability import (
    ProtectionObservability,
    ProtectionSnapshot,
    get_protection_observability,
)


@dataclass(frozen=True)
class ApplicationHealth:
    status: str
    redis: RedisHealthStatus
    protections: dict[str, ProtectionSnapshot]


@dataclass(frozen=True)
class ApplicationReadiness:
    ready: bool
    dependencies: dict[str, str]
    failure_codes: list[str]


class ReadinessService:
    def __init__(self, probes: dict[str, ReadinessProbe]) -> None:
        self._probes = probes

    def inspect(self) -> ApplicationReadiness:
        dependencies: dict[str, str] = {}
        failure_codes: list[str] = []
        for name, probe in self._probes.items():
            try:
                result = probe.check()
            except Exception:
                dependencies[name] = "failed"
                failure_codes.append(f"{name.upper()}_CHECK_FAILED")
                continue
            dependencies[name] = "ok" if result.ok else "failed"
            if not result.ok and result.failure_code:
                failure_codes.append(result.failure_code)
        return ApplicationReadiness(
            ready=not failure_codes,
            dependencies=dependencies,
            failure_codes=failure_codes,
        )

    def close(self) -> None:
        for probe in self._probes.values():
            try:
                probe.close()
            except Exception:
                pass


def create_readiness_service(
    settings: Settings,
    redis: RedisInfrastructure,
) -> ReadinessService:
    database_probe: ReadinessProbe
    if settings.database_url is None:
        database_probe = FailedReadinessProbe("MYSQL_NOT_CONFIGURED")
    else:
        try:
            database_probe = DatabaseReadinessProbe(
                settings.database_url.get_secret_value(),
                settings.readiness_timeout_seconds,
            )
        except Exception:
            database_probe = FailedReadinessProbe("MYSQL_CONFIGURATION_INVALID")
    return ReadinessService(
        {
            "mysql": database_probe,
            "redis": RedisReadinessProbe(redis),
            "chroma": WritableDirectoryReadinessProbe(
                settings.chroma_persist_dir,
                "CHROMA_DIRECTORY_UNAVAILABLE",
            ),
            "media": WritableDirectoryReadinessProbe(
                settings.media_asset_dir,
                "MEDIA_DIRECTORY_UNAVAILABLE",
            ),
        }
    )


class HealthService:
    def __init__(
        self,
        redis: RedisInfrastructure,
        protections: ProtectionObservability,
    ) -> None:
        self.redis = redis
        self.protections = protections

    def inspect(self) -> ApplicationHealth:
        redis_status = self.redis.health_status()
        return ApplicationHealth(
            status="ok",
            redis=redis_status,
            protections=self.protections.snapshot(redis_status),
        )


def get_redis_infrastructure(request: Request) -> RedisInfrastructure:
    return request.app.state.redis_infrastructure


def get_health_service(
    redis: RedisInfrastructure = Depends(get_redis_infrastructure),
    protections: ProtectionObservability = Depends(get_protection_observability),
) -> HealthService:
    return HealthService(redis, protections)


def get_readiness_service(request: Request) -> ReadinessService:
    return request.app.state.readiness_service
