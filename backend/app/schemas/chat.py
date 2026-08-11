"""问答接口的请求、回答和引用来源结构。"""

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    """用户提交的问题及希望检索的片段数量。"""

    question: str = Field(default="", max_length=2000, description="用户问题；有图片时可为空")
    top_k: int = Field(default=4, ge=1, le=10, description="检索片段数量")
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)
    model_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        return cleaned_value

    @field_validator("attachment_ids")
    @classmethod
    def attachments_must_be_unique(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 36 for value in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("附件标识无效或重复")
        return cleaned

    @model_validator(mode="after")
    def require_text_or_image(self):
        if not self.question and not self.attachment_ids:
            raise ValueError("问题或图片至少提供一项")
        return self


class SourceItem(BaseModel):
    """回答所依据的一个知识库片段。"""

    file_name: str
    page: int | None = None
    content: str
    document_id: str | None = None
    chunk_id: str | None = None


class ChatResponse(BaseModel):
    """RAG 问答成功后的统一响应。"""

    answer: str
    sources: list[SourceItem]
    request_id: str
    disclaimer: str = "仅供学习和信息检索，不构成医疗建议。"


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str
