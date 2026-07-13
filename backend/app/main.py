"""FastAPI 应用入口：创建应用，并把各业务路由组装进来。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers


def create_app() -> FastAPI:
    """创建 FastAPI 应用，便于以后测试和扩展配置。"""
    settings = get_settings()
    application = FastAPI(
        title="Medical RAG Assistant API",
        description="医疗知识库智能问答系统后端接口（仅供学习和信息检索）",
        version="0.1.0",
    )
    # 只允许本地 Vue 开发服务器跨域访问，模型密钥仍只保留在后端。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(conversations_router, prefix="/api/v1")
    application.include_router(documents_router, prefix="/api/v1")
    register_exception_handlers(application)
    return application


app = create_app()
