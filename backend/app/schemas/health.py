"""健康检查接口的数据结构。"""

from typing import Literal

from pydantic import BaseModel


class DependencyHealth(BaseModel):
    status: Literal["ok", "disabled", "degraded"]


class ProtectionHealth(BaseModel):
    policy: Literal["local_fallback", "fail_closed"]
    mode: Literal["redis", "local_fallback", "available", "unavailable"]
    success_events: int
    failure_events: int
    recovery_events: int
    last_error_type: str | None


class RedisProtectionHealth(BaseModel):
    rate_limit: ProtectionHealth
    upload_concurrency: ProtectionHealth
    generation_lock: ProtectionHealth
    idempotency: ProtectionHealth


class HealthDependencies(BaseModel):
    redis: DependencyHealth
    protections: RedisProtectionHealth


class HealthResponse(BaseModel):
    """应用可用性和可选基础设施状态，不包含连接信息。"""

    status: Literal["ok"]
    dependencies: HealthDependencies
