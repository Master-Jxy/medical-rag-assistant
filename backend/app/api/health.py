"""健康检查接口。"""

from fastapi import APIRouter, Depends, Response, status

from app.schemas.health import (
    DependencyHealth,
    HealthDependencies,
    HealthResponse,
    LivenessResponse,
    ProtectionHealth,
    ReadinessResponse,
    RedisProtectionHealth,
)
from app.services.health_service import (
    HealthService,
    ReadinessService,
    get_health_service,
    get_readiness_service,
)

router = APIRouter(tags=["系统状态"])
probe_router = APIRouter(tags=["系统状态"])


@probe_router.get("/livez", response_model=LivenessResponse)
def liveness_check() -> LivenessResponse:
    return LivenessResponse(status="ok")


@probe_router.get("/readyz", response_model=ReadinessResponse)
def readiness_check(
    response: Response,
    service: ReadinessService = Depends(get_readiness_service),
) -> ReadinessResponse:
    result = service.inspect()
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if result.ready else "not_ready",
        dependencies=result.dependencies,
        failure_codes=result.failure_codes,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="检查后端服务是否正常运行",
)
def health_check(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """不初始化数据库、向量库或模型；Redis 最多执行一次有界 ping。"""
    result = service.inspect()
    protections = {
        feature: ProtectionHealth(**snapshot.__dict__)
        for feature, snapshot in result.protections.items()
    }
    return HealthResponse(
        status="ok",
        dependencies=HealthDependencies(
            redis=DependencyHealth(status=result.redis.value),
            protections=RedisProtectionHealth(**protections),
        ),
    )
