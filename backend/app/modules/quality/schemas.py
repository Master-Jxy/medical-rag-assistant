"""质量反馈与复核API契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionCategory = Literal[
    "symptom", "medication", "test", "emergency", "prevention", "general"
]
IssueCategory = Literal[
    "inaccurate", "irrelevant", "incomplete", "unsafe", "citation", "other"
]


class FeedbackUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Literal["up", "down"]
    question_category: QuestionCategory = "general"
    issue_category: IssueCategory | None = None
    comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def downvote_requires_issue(self):
        if self.rating == "down" and self.issue_category is None:
            raise ValueError("点踩必须选择问题类型")
        if self.rating == "up":
            self.issue_category = None
        self.comment = self.comment.strip() if self.comment else None
        return self


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    rating: str
    question_category: str
    issue_category: str | None
    comment: str | None
    review_status: str
    updated_at: datetime


class FeedbackReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "dismissed"]
    note: str = Field(min_length=1, max_length=500)


class DailyQualityPoint(BaseModel):
    date: str
    total: int
    positive: int
    negative: int


class QualityOverview(BaseModel):
    total: int
    positive: int
    negative: int
    pending_review: int
    positive_rate: float | None
    issue_counts: dict[str, int]
    question_counts: dict[str, int]
    daily_counts: list[DailyQualityPoint]


class ReviewQueueItem(FeedbackResponse):
    created_at: datetime


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    offset: int
    limit: int


class ReviewDetail(BaseModel):
    feedback: ReviewQueueItem
    conversation_id: str
    question_excerpt: str
    answer_excerpt: str
    source_names: list[str]
