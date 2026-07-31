from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user, require_admin, require_super_admin
from app.modules.auth.schemas import UserResponse
from app.modules.usage.query_service import UsageQueryService
from app.modules.usage.quota_service import QuotaApplicationService
from app.modules.usage.admin_service import UsageAdminService
from app.modules.usage.schemas import QuotaAdjustmentRequest
from app.core.config import get_settings
from app.modules.usage.contracts import resolve_quota_policy_mode

router = APIRouter(tags=["用量与额度"])

@router.get("/profile/quota")
def profile_quota(current_user: UserResponse = Depends(get_current_user), session: Session = Depends(get_db_session)):
    settings = get_settings()
    return QuotaApplicationService(
        session,
        default_plan_code=settings.default_quota_plan_code,
        policy_mode=resolve_quota_policy_mode(
            settings.quota_policy_mode,
            settings.quota_enforcement_enabled,
        ),
    ).current(current_user.id)

@router.get("/profile/usage/summary")
def profile_usage_summary(days: int = Query(30, ge=1, le=90), current_user: UserResponse = Depends(get_current_user), session: Session = Depends(get_db_session)):
    return UsageQueryService(session).summary(current_user.id, days)

@router.get("/profile/usage/trend")
def profile_usage_trend(days: int = Query(30, ge=1, le=90), current_user: UserResponse = Depends(get_current_user), session: Session = Depends(get_db_session)):
    return {"items": UsageQueryService(session).trend(current_user.id, days)}

@router.get("/profile/usage/records")
def profile_usage_records(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), current_user: UserResponse = Depends(get_current_user), session: Session = Depends(get_db_session)):
    return UsageQueryService(session).records(current_user.id, offset, limit)

@router.get("/profile/usage/distribution")
def profile_usage_distribution(days: int = Query(30, ge=1, le=90), current_user: UserResponse = Depends(get_current_user), session: Session = Depends(get_db_session)):
    return UsageQueryService(session).distribution(current_user.id, days)

@router.get("/admin/usage/overview")
def admin_usage_overview(days: int = Query(30, ge=1, le=90), _: UserResponse = Depends(require_admin), session: Session = Depends(get_db_session)):
    return UsageQueryService(session).admin_overview(days)

@router.get("/admin/usage/records")
def admin_usage_records(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), _: UserResponse = Depends(require_admin), session: Session = Depends(get_db_session)):
    return UsageQueryService(session).records(None, offset, limit)

@router.get("/admin/usage/trend")
def admin_usage_trend(days: int = Query(30, ge=1, le=90), _: UserResponse = Depends(require_admin), session: Session = Depends(get_db_session)):
    return {"items": UsageQueryService(session).trend(None, days)}

@router.get("/admin/usage/users")
def admin_usage_users(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), _: UserResponse = Depends(require_admin), session: Session = Depends(get_db_session)):
    return UsageAdminService(session).users(offset=offset, limit=limit)

@router.get("/admin/usage/records/filter")
def admin_usage_records_filtered(
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
    user_id: str | None = None, model_name: str | None = None,
    surface: str | None = Query(default=None, pattern="^(rag|agent|memory)$"),
    status: str | None = Query(default=None, pattern="^(completed|failed|cancelled)$"),
    _: UserResponse = Depends(require_admin), session: Session = Depends(get_db_session),
):
    return UsageQueryService(session).records(user_id, offset, limit, model_name=model_name, surface=surface, status=status)

@router.put("/admin/users/{user_id}/quota")
def adjust_user_quota(
    user_id: str, payload: QuotaAdjustmentRequest,
    current_user: UserResponse = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
):
    return UsageAdminService(session).adjust(
        actor_user_id=current_user.id, target_user_id=user_id, payload=payload)
