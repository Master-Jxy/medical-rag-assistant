"""超级管理员用户治理接口。"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.administration import UserAdministrationService
from app.modules.auth.dependencies import require_super_admin
from app.modules.auth.roles import UserRole
from app.modules.auth.schemas import (
    UserListResponse,
    UserResponse,
    UserRoleUpdate,
    UserStatusUpdate,
)

router = APIRouter(prefix="/super-admin/users", tags=["超级管理员用户治理"])


def get_user_administration_service(
    session: Session = Depends(get_db_session),
) -> UserAdministrationService:
    return UserAdministrationService(session, SqlAlchemyAuditRecorder(session))


@router.get("", response_model=UserListResponse)
def list_users(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=320),
    role: UserRole | None = None,
    is_active: bool | None = None,
    _actor: UserResponse = Depends(require_super_admin),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> UserListResponse:
    return service.list_users(
        offset=offset,
        limit=limit,
        search=search,
        role=role,
        is_active=is_active,
    )


@router.patch("/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    request: Request,
    actor: UserResponse = Depends(require_super_admin),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> UserResponse:
    return service.update_role(
        user_id,
        payload.role,
        actor_user_id=actor.id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.patch("/{user_id}/status", response_model=UserResponse)
def update_user_status(
    user_id: str,
    payload: UserStatusUpdate,
    request: Request,
    actor: UserResponse = Depends(require_super_admin),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> UserResponse:
    return service.update_status(
        user_id,
        payload.is_active,
        actor_user_id=actor.id,
        request_id=getattr(request.state, "request_id", None),
    )
