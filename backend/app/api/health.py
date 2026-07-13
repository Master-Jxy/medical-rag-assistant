"""健康检查接口。"""

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["系统状态"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="检查后端服务是否正常运行",
)
def health_check() -> HealthResponse:
    """返回固定状态；不调用数据库、向量库或大模型。"""
    return HealthResponse(status="ok")
