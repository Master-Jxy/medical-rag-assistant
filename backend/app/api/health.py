"""健康检查接口。"""

from fastapi import APIRouter, Depends

from app.schemas.health import (
    DependencyHealth,
    HealthDependencies,
    HealthResponse,
    ProtectionHealth,
    RedisProtectionHealth,
)
from app.services.health_service import HealthService, get_health_service

router = APIRouter(tags=["系统状态"])


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
