"""当前用户的资料提交查询接口。"""

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.core.config import Settings, get_settings
from app.infrastructure.web_snapshot_fetcher import HttpxWebSnapshotFetchAdapter
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.modules.knowledge.parser import LocalDocumentParser
from app.modules.knowledge.schemas import (
    MySubmissionListResponse,
    SubmissionCreateResponse,
    WebSnapshotSubmissionRequest,
)
from app.modules.knowledge.submission_service import KnowledgeSubmissionService
from app.modules.knowledge.submission_queries import MySubmissionQueryService
from app.services.upload_protection_service import (
    UploadProtectionService,
    get_upload_protection_service,
)

router = APIRouter(prefix="/knowledge/submissions", tags=["我的资料"])


def get_submission_service(
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    protection: UploadProtectionService = Depends(get_upload_protection_service),
) -> KnowledgeSubmissionService:
    return KnowledgeSubmissionService(
        session,
        settings,
        LocalDocumentParser(),
        protection,
        HttpxWebSnapshotFetchAdapter(settings),
    )


@router.post("", response_model=SubmissionCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_submission(
    file: UploadFile = File(description="不超过10 MB的PDF、TXT、DOCX、Markdown或HTML文件"),
    current_user: UserResponse = Depends(get_current_user),
    service: KnowledgeSubmissionService = Depends(get_submission_service),
) -> SubmissionCreateResponse:
    return await service.submit(current_user.id, file)


@router.post(
    "/web-snapshots",
    response_model=SubmissionCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_web_snapshot_submission(
    payload: WebSnapshotSubmissionRequest,
    current_user: UserResponse = Depends(get_current_user),
    service: KnowledgeSubmissionService = Depends(get_submission_service),
) -> SubmissionCreateResponse:
    return await service.submit_url(current_user.id, payload.url)


@router.get("", response_model=MySubmissionListResponse)
def list_my_submissions(
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MySubmissionListResponse:
    return MySubmissionQueryService(session).list_for_user(current_user.id)


@router.post("/{submission_id}/withdraw", response_model=SubmissionCreateResponse)
def withdraw_submission(
    submission_id: str,
    current_user: UserResponse = Depends(get_current_user),
    service: KnowledgeSubmissionService = Depends(get_submission_service),
) -> SubmissionCreateResponse:
    return service.withdraw(current_user.id, submission_id)
