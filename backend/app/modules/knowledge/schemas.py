"""知识治理接口契约。"""

from datetime import datetime

from pydantic import BaseModel


class MySubmissionItem(BaseModel):
    submission_id: str
    file_name: str
    status: str
    rejection_reason: str | None = None
    failure_reason: str | None = None
    can_withdraw: bool
    submitted_at: datetime
    document_id: str | None = None


class MySubmissionListResponse(BaseModel):
    items: list[MySubmissionItem]
    total: int


class SubmissionCreateResponse(MySubmissionItem):
    message: str = "资料已提交，等待管理员审核"
