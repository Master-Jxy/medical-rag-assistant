"""API contracts for private chat images."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_name: str
    mime_type: str
    byte_size: int
    width: int
    height: int
    status: str
    expires_at: datetime
    preview_url: str


class MediaDeleteResponse(BaseModel):
    id: str
    status: str = "deleted"


class MessageAttachmentResponse(BaseModel):
    id: str
    media_asset_id: str
    position: int
    original_name: str
    mime_type: str
    byte_size: int
    width: int
    height: int
    preview_url: str
