"""Application service for upload, ownership, deletion and expiry."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import MediaConflictError, MediaNotFoundError
from app.modules.media.models import MediaAsset
from app.modules.media.repository import MediaRepository
from app.modules.media.schemas import MediaAssetResponse, MediaDeleteResponse
from app.modules.media.storage import PrivateMediaStorage


class MediaAssetService:
    def __init__(self, session: Session, settings: Settings, storage: PrivateMediaStorage | None = None) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage or PrivateMediaStorage(settings)
        self.repository = MediaRepository(session)

    async def upload(self, user_id: str, file) -> MediaAssetResponse:
        data = await file.read(self.settings.vision_max_image_bytes + 1)
        stored = self.storage.store(original_name=file.filename or "image", claimed_mime=file.content_type, data=data)
        asset = MediaAsset(
            user_id=user_id,
            original_name=Path(file.filename or "image").name,
            mime_type=stored.mime_type,
            byte_size=stored.byte_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
            storage_key=stored.storage_key,
            expires_at=datetime.now(timezone.utc) + timedelta(days=self.settings.media_retention_days),
        )
        try:
            self.repository.add(asset)
            self.session.commit()
            self.session.refresh(asset)
        except Exception:
            self.session.rollback()
            self.storage.delete(stored.storage_key)
            raise
        return self._response(asset)

    def owned_asset(self, user_id: str, asset_id: str, *, allow_attached: bool = True) -> MediaAsset:
        asset = self.repository.owned(user_id, asset_id)
        allowed = {"uploaded", "attached"} if allow_attached else {"uploaded"}
        if asset is None or asset.status not in allowed:
            raise MediaNotFoundError()
        return asset

    def preview(self, user_id: str, asset_id: str) -> tuple[Path, str, str]:
        asset = self.owned_asset(user_id, asset_id)
        path = self.storage.resolve(asset.storage_key)
        if not path.is_file() or path.is_symlink():
            raise MediaNotFoundError()
        return path, asset.mime_type, asset.original_name

    def delete(self, user_id: str, asset_id: str) -> MediaDeleteResponse:
        asset = self.repository.owned(user_id, asset_id, lock=True)
        if asset is None or asset.status in {"deleted", "expired"}:
            raise MediaNotFoundError()
        if self.repository.attachment_for_asset(asset.id) is not None or asset.status == "attached":
            raise MediaConflictError("已发送的图片随会话保留，不能单独删除")
        self.storage.delete(asset.storage_key)
        asset.status = "deleted"
        self.session.commit()
        return MediaDeleteResponse(id=asset.id)

    def cleanup_expired(self, *, limit: int = 100) -> int:
        assets = list(self.session.scalars(select(MediaAsset).where(MediaAsset.status == "uploaded", MediaAsset.expires_at <= datetime.now(timezone.utc)).limit(limit)))
        for asset in assets:
            self.storage.delete(asset.storage_key)
            asset.status = "expired"
        self.session.commit()
        return len(assets)

    @staticmethod
    def _response(asset: MediaAsset) -> MediaAssetResponse:
        return MediaAssetResponse(
            id=asset.id, original_name=asset.original_name, mime_type=asset.mime_type,
            byte_size=asset.byte_size, width=asset.width, height=asset.height,
            status=asset.status, expires_at=asset.expires_at,
            preview_url=f"/api/v1/media/assets/{asset.id}/preview",
        )
