"""当前登录用户的个人中心与个人统计。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.services.profile_query_service import PersonalStatsResponse, ProfileQueryService

router = APIRouter(tags=["个人中心"])


@router.get("/profile", response_model=UserResponse)
def get_profile(
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> UserResponse:
    return ProfileQueryService(session).get_profile(current_user)


@router.get("/me/stats", response_model=PersonalStatsResponse)
def get_personal_stats(
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PersonalStatsResponse:
    return ProfileQueryService(session).get_stats(current_user.id)
