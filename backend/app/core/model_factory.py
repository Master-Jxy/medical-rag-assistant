"""创建阿里云百炼聊天模型和 Embedding 模型。"""

from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings

from app.core.config import Settings, get_settings


def create_chat_model(settings: Settings | None = None) -> ChatTongyi:
    """创建聊天模型；限制重试次数，防止异常时循环请求产生额外费用。"""
    current_settings = settings or get_settings()
    return ChatTongyi(
        model=current_settings.chat_model_name,
        api_key=current_settings.require_dashscope_api_key(),
        streaming=True,
        max_retries=2,
    )


def create_embedding_model(settings: Settings | None = None) -> DashScopeEmbeddings:
    """创建文本向量模型，供 Chroma 把问题转换为查询向量。"""
    current_settings = settings or get_settings()
    return DashScopeEmbeddings(
        model=current_settings.embedding_model_name,
        dashscope_api_key=current_settings.require_dashscope_api_key(),
        max_retries=2,
    )
