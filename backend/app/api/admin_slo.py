"""管理员只读 SLO 与数据卫生检查。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.schemas.slo import SloChecksResponse
from app.services.slo_service import SloChecksService

router = APIRouter(prefix="/admin/telemetry", tags=["管理员SLO"])


@router.get("/slo", response_model=SloChecksResponse)
def get_slo_checks(
    _admin: UserResponse = Depends(require_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SloChecksResponse:
    return SloChecksService(session, settings).get_checks()
