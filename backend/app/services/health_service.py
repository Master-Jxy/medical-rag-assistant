"""应用健康状态用例，组合基础设施状态但不暴露连接信息。"""

from dataclasses import dataclass

from fastapi import Depends, Request

from app.infrastructure.redis import RedisHealthStatus, RedisInfrastructure
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
