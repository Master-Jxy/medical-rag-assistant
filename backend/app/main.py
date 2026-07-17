"""FastAPI 应用入口：创建应用，并把各业务路由组装进来。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.admin_documents import router as admin_documents_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.infrastructure.redis import RedisInfrastructure
from app.infrastructure.local_rate_limit import BoundedLocalRateLimitAdapter
from app.infrastructure.local_concurrency_limit import (
    BoundedLocalConcurrencyLimitAdapter,
)
from app.modules.auth.rate_limit import AuthRateLimitService
from app.modules.auth.router import router as auth_router
from app.services.chat_rate_limit_service import ChatRateLimitService
from app.services.generation_lock_service import GenerationLockService
from app.services.idempotency_service import IdempotencyService
from app.services.stream_cancellation_service import StreamCancellationService
from app.services.protection_observability import ProtectionObservability
from app.services.concurrency_limit_service import ConcurrencyLimitService
from app.services.rate_limit_service import RateLimitService
from app.services.upload_protection_service import UploadProtectionService


def create_app(
    redis_infrastructure: RedisInfrastructure | None = None,
    auth_rate_limit_service: AuthRateLimitService | None = None,
    chat_rate_limit_service: ChatRateLimitService | None = None,
    upload_protection_service: UploadProtectionService | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，便于以后测试和扩展配置。"""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            application.state.redis_infrastructure.close()

    application = FastAPI(
        title="Medical RAG Assistant API",
        description="医疗知识库智能问答系统后端接口（仅供学习和信息检索）",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.redis_infrastructure = (
        redis_infrastructure or RedisInfrastructure(settings)
    )
    application.state.protection_observability = ProtectionObservability(
        redis_configured=settings.optional_redis_url() is not None
    )
    application.state.generation_lock_service = GenerationLockService(
        application.state.redis_infrastructure,
        settings,
        application.state.protection_observability,
    )
    application.state.idempotency_service = IdempotencyService(
        application.state.redis_infrastructure,
        settings,
        application.state.protection_observability,
    )
    application.state.stream_cancellation_service = StreamCancellationService()
    local_rate_limiter = BoundedLocalRateLimitAdapter(
        settings.auth_rate_limit_fallback_max_keys
    )
    rate_limiter = RateLimitService(
        application.state.redis_infrastructure,
        local_rate_limiter,
        application.state.protection_observability,
    )
    application.state.auth_rate_limit_service = (
        auth_rate_limit_service
        or AuthRateLimitService(rate_limiter, settings)
    )
    application.state.chat_rate_limit_service = (
        chat_rate_limit_service
        or ChatRateLimitService(rate_limiter, settings)
    )
    concurrency_limiter = ConcurrencyLimitService(
        application.state.redis_infrastructure,
        BoundedLocalConcurrencyLimitAdapter(
            settings.auth_rate_limit_fallback_max_keys
        ),
        application.state.protection_observability,
    )
    application.state.upload_protection_service = (
        upload_protection_service
        or UploadProtectionService(rate_limiter, concurrency_limiter, settings)
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
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(admin_documents_router, prefix="/api/v1")
    register_exception_handlers(application)
    return application


app = create_app()
