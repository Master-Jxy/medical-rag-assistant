"""Authenticated private image upload, preview and draft deletion endpoints."""

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.modules.media.schemas import MediaAssetResponse, MediaDeleteResponse
from app.modules.media.service import MediaAssetService

router = APIRouter(prefix="/media/assets", tags=["私有聊天图片"])


def get_media_service(session: Session = Depends(get_db_session), settings: Settings = Depends(get_settings)) -> MediaAssetService:
    return MediaAssetService(session, settings)


@router.post("", response_model=MediaAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(file: UploadFile = File(description="JPG/PNG/WEBP, max 10 MiB"), current_user: UserResponse = Depends(get_current_user), service: MediaAssetService = Depends(get_media_service)) -> MediaAssetResponse:
    return await service.upload(current_user.id, file)


@router.get("/{asset_id}/preview", response_class=FileResponse)
def preview_media(asset_id: str, current_user: UserResponse = Depends(get_current_user), service: MediaAssetService = Depends(get_media_service)) -> FileResponse:
    path, mime_type, name = service.preview(current_user.id, asset_id)
    return FileResponse(path, media_type=mime_type, filename=name, content_disposition_type="inline", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/{asset_id}", response_model=MediaDeleteResponse)
def delete_media(asset_id: str, current_user: UserResponse = Depends(get_current_user), service: MediaAssetService = Depends(get_media_service)) -> MediaDeleteResponse:
    return service.delete(current_user.id, asset_id)
