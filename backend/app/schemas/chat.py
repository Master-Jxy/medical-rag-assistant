"""问答接口的请求、回答和引用来源结构。"""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """用户提交的问题及希望检索的片段数量。"""

    question: str = Field(min_length=1, max_length=2000, description="用户问题")
    top_k: int = Field(default=4, ge=1, le=10, description="检索片段数量")

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("问题不能为空")
        return cleaned_value


class SourceItem(BaseModel):
    """回答所依据的一个知识库片段。"""

    file_name: str
    page: int | None = None
    content: str


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
