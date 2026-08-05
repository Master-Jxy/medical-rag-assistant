"""管理员资料审核契约。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.knowledge.metadata_suggestions import MetadataSuggestionItem


class DuplicateCandidateItem(BaseModel):
    duplicate_type: str
    candidate_document_id: str
    candidate_file_name: str
    candidate_version: int
    score: float | None = None
    distance: int | None = None
    threshold: int | None = None
    reason: str


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
    duplicate_candidates: list[DuplicateCandidateItem] = Field(default_factory=list)
    duplicate_decision: str | None = None
    duplicate_target_document_id: str | None = None
    normalized_text_hash_version: str | None = None
    near_duplicate_fingerprint_version: str | None = None
    created_at: datetime
    updated_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewItem]
    total: int
    offset: int
    limit: int


class RejectSubmissionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class ApproveAsVersionRequest(BaseModel):
    supersedes_document_id: str = Field(min_length=1, max_length=36)
    change_reason: str = Field(min_length=2, max_length=500)


class ApprovalResponse(BaseModel):
    submission: ReviewItem
    job_id: str | None = None
