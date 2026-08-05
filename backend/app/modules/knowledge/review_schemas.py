"""管理员资料审核契约。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.knowledge.metadata_suggestions import MetadataSuggestionItem


class ReviewItem(BaseModel):
    submission_id: str
    submitter_id: str | None
    file_name: str
    content_hash: str
    size_bytes: int
    status: str
    preview_text: str | None
    preview_pages: int | None
    parse_warnings: list[str]
    parse_quality: dict[str, object] = Field(default_factory=dict)
    rejection_reason: str | None
    failure_reason: str | None
    document_id: str | None
    metadata_suggestion: MetadataSuggestionItem | None = None
    created_at: datetime
    updated_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewItem]
    total: int
    offset: int
    limit: int


class RejectSubmissionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class ApprovalResponse(BaseModel):
    submission: ReviewItem
    job_id: str | None = None
