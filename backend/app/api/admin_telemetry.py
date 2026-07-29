"""管理员只读运行统计；不返回日志全文或业务正文。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.schemas.telemetry import TelemetryStatsResponse
from app.services.telemetry_service import TelemetryStatsService

router = APIRouter(prefix="/admin/telemetry", tags=["管理员运行统计"])


def get_telemetry_stats_service(
    request: Request,
    session: Session = Depends(get_db_session),
) -> TelemetryStatsService:
    """在装配边界把应用级Telemetry Port交给纯业务Service。"""
    return TelemetryStatsService(request.app.state.telemetry, session)


@router.get("/stats", response_model=TelemetryStatsResponse)
def get_telemetry_stats(
    _admin: UserResponse = Depends(require_admin),
    service: TelemetryStatsService = Depends(get_telemetry_stats_service),
) -> TelemetryStatsResponse:
    return service.get_stats()
