"""会话、消息和引用来源的接口数据结构。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.chat import ChatResponse


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("会话标题不能为空")
        return cleaned


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("会话标题不能为空")
        return cleaned


class MessageSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    file_name: str
    page: int | None
    content: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence: int
    role: str
    content: str
    status: str
    request_id: str | None
    created_at: datetime
    sources: list[MessageSourceResponse]


class ConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class ConversationDetail(ConversationSummary):
    messages: list[MessageResponse]


class ConversationDeleteResponse(BaseModel):
    conversation_id: str
    message: str = "会话已删除"


class ConversationChatResponse(ChatResponse):
    """带持久化消息标识的普通问答响应。"""

    conversation_id: str
    user_message_id: str
    assistant_message_id: str
