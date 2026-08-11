"""创建阿里云百炼聊天模型和 Embedding 模型。"""

from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings

from app.core.config import Settings, get_settings
from app.modules.model_gateway.contracts import (
    ModelCapability,
    ModelRoute,
    ModelRouteRequest,
    ModelSurface,
)
from app.modules.model_gateway.policy import StaticModelRoutePolicy


def resolve_model_route(
    settings: Settings,
    *,
    surface: ModelSurface,
    capabilities: frozenset[ModelCapability],
    model_id: str | None = None,
) -> ModelRoute:
    return StaticModelRoutePolicy.from_settings(settings).resolve(
        ModelRouteRequest(
            surface=surface,
            task_kind="runtime",
            required_capabilities=capabilities,
            selected_model_id=model_id,
            user_role="system",
        )
    ).primary


def create_chat_model(
    settings: Settings | None = None,
    *,
    surface: ModelSurface = ModelSurface.RAG,
    model_id: str | None = None,
) -> ChatTongyi:
    """创建聊天模型；重试次数由受限配置控制。"""
    current_settings = settings or get_settings()
    route = resolve_model_route(
        current_settings,
        surface=surface,
        capabilities=frozenset({ModelCapability.TEXT}),
        model_id=model_id,
    )
    return ChatTongyi(
        model=route.model_name,
        api_key=current_settings.require_dashscope_api_key(),
        streaming=True,
        max_retries=current_settings.dashscope_max_retries,
    )


def create_embedding_model(settings: Settings | None = None) -> DashScopeEmbeddings:
    """创建文本向量模型，供 Chroma 把问题转换为查询向量。"""
    current_settings = settings or get_settings()
    return DashScopeEmbeddings(
        model=current_settings.embedding_model_name,
        dashscope_api_key=current_settings.require_dashscope_api_key(),
        max_retries=current_settings.dashscope_max_retries,
    )
