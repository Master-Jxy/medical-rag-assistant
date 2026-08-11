"""管理员任务中心与审计中心接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.audit.schemas import AuditEventListResponse
from app.modules.audit.service import AuditQueryService
from app.modules.auth.dependencies import require_admin
from app.modules.auth.schemas import UserResponse
from app.modules.jobs.schemas import JobItem, JobListResponse
from app.modules.jobs.service import JobQueryService, JobQueueService

router = APIRouter(prefix="/admin", tags=["管理员任务与审计"])


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    status: str | None = Query(default=None, max_length=20),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _admin: UserResponse = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> JobListResponse:
    return JobQueryService(session).list_jobs(
        status=status, offset=offset, limit=limit
    )


@router.post("/jobs/{job_id}/retry", response_model=JobItem)
def retry_job(
    job_id: str,
    _admin: UserResponse = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> JobItem:
    job = JobQueueService(session).retry(job_id)
    return JobQueryService.to_item(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobItem)
def cancel_job(
    job_id: str,
    _admin: UserResponse = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> JobItem:
    job = JobQueueService(session).request_cancel(job_id)
    return JobQueryService.to_item(job)


@router.get("/audit", response_model=AuditEventListResponse)
def list_audit_events(
    action: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    admin: UserResponse = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> AuditEventListResponse:
    return AuditQueryService(session).list_events(
        viewer_role=admin.role,
        action=action,
        offset=offset,
        limit=limit,
    )
