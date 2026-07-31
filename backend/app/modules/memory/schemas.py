"""用户可控记忆API契约。"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemorySettingResponse(BaseModel):
    enabled: bool
    auto_extract_enabled: bool = False


class MemorySettingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    auto_extract_enabled: bool | None = None


class UserMemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=1000)
    category: str = Field(default="explicit_note", pattern="^(profile|preference|goal|ongoing_task|health_context|explicit_note)$")

    @field_validator("label", "content")
    @classmethod
    def strip_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("记忆内容不能为空")
        return value


class UserMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    label: str
    content: str
    category: str = "explicit_note"
    status: str = "active"
    source_type: str = "manual"
    supersedes_id: str | None = None
    created_at: datetime
    updated_at: datetime


class UserMemoryListResponse(BaseModel):
    items: list[UserMemoryResponse]
