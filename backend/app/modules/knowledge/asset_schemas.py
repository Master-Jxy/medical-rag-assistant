"""管理员知识资产接口契约。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class KnowledgeAssetItem(BaseModel):
    document_id: str
    file_name: str
    status: str
    source: str | None
    tags: list[str]
    version: int
    replaces_document_id: str | None
    chunk_count: int
    updated_at: datetime


class KnowledgeAssetListResponse(BaseModel):
    items: list[KnowledgeAssetItem]
    total: int
    offset: int
    limit: int


class AssetMetadataUpdate(BaseModel):
    source: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            item = value.strip()
            if not item or len(item) > 50:
                raise ValueError("标签必须为1-50个非空字符")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class ReplacementRequest(BaseModel):
    replacement_document_id: str = Field(min_length=1, max_length=36)
