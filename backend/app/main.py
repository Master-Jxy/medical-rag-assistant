"""FastAPI 应用入口：创建应用，并把各业务路由组装进来。"""

from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.admin_documents import router as admin_documents_router
from app.api.admin_telemetry import router as admin_telemetry_router
from app.api.admin_reviews import router as admin_reviews_router
from app.api.admin_knowledge_assets import router as admin_knowledge_assets_router
from app.api.admin_operations import router as admin_operations_router
from app.api.super_admin_users import router as super_admin_users_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.knowledge_submissions import router as knowledge_submissions_router
from app.api.profile import router as profile_router
from app.api.agent import router as agent_router
from app.api.quality import router as quality_router
from app.api.memory import router as memory_router
from app.api.knowledge_trace import router as knowledge_trace_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.request_context import new_request_id, reset_request_id, set_request_id
from app.infrastructure.telemetry import create_local_telemetry
from app.ports.telemetry import TelemetryEvent, TelemetryPort, emit_safely
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
from app.modules.agent.cancellation import AgentCancellationService


def create_app(
    redis_infrastructure: RedisInfrastructure | None = None,
    auth_rate_limit_service: AuthRateLimitService | None = None,
    chat_rate_limit_service: ChatRateLimitService | None = None,
    upload_protection_service: UploadProtectionService | None = None,
    telemetry: TelemetryPort | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，便于以后测试和扩展配置。"""
    current_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            application.state.redis_infrastructure.close()
            close_telemetry = getattr(application.state.telemetry, "close", None)
            if callable(close_telemetry):
                try:
                    close_telemetry()
                except Exception:
                    pass

    application = FastAPI(
        title="Medical RAG Assistant API",
        description="医疗知识库智能问答系统后端接口（仅供学习和信息检索）",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.telemetry = telemetry or create_local_telemetry(current_settings)
    application.state.agent_cancellation_service = AgentCancellationService()

    @application.middleware("http")
    async def telemetry_middleware(request: Request, call_next):
        request_id = new_request_id()
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started = monotonic()
        status_code = 500
        error_type = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            emit_safely(
                application.state.telemetry,
                TelemetryEvent.create(
                    request_id=request_id,
                    event_name="http_request",
                    result="success" if status_code < 400 else "failure",
                    route=request.url.path,
                    user_id=getattr(request.state, "user_id", None),
                    status_code=status_code,
                    error_type=error_type,
                    duration_ms=round((monotonic() - started) * 1000, 3),
                ),
            )
            reset_request_id(token)
    application.state.redis_infrastructure = (
        redis_infrastructure or RedisInfrastructure(current_settings)
    )
    application.state.protection_observability = ProtectionObservability(
        redis_configured=current_settings.optional_redis_url() is not None,
        telemetry=application.state.telemetry,
    )
    application.state.generation_lock_service = GenerationLockService(
        application.state.redis_infrastructure,
        current_settings,
        application.state.protection_observability,
    )
    application.state.idempotency_service = IdempotencyService(
        application.state.redis_infrastructure,
        current_settings,
        application.state.protection_observability,
    )
    application.state.stream_cancellation_service = StreamCancellationService(
        application.state.telemetry
    )
    local_rate_limiter = BoundedLocalRateLimitAdapter(
        current_settings.auth_rate_limit_fallback_max_keys
    )
    rate_limiter = RateLimitService(
        application.state.redis_infrastructure,
        local_rate_limiter,
        application.state.protection_observability,
    )
    application.state.auth_rate_limit_service = (
        auth_rate_limit_service
        or AuthRateLimitService(rate_limiter, current_settings)
    )
    application.state.chat_rate_limit_service = (
        chat_rate_limit_service
        or ChatRateLimitService(rate_limiter, current_settings)
    )
    concurrency_limiter = ConcurrencyLimitService(
        application.state.redis_infrastructure,
        BoundedLocalConcurrencyLimitAdapter(
            current_settings.auth_rate_limit_fallback_max_keys
        ),
        application.state.protection_observability,
    )
    application.state.upload_protection_service = (
        upload_protection_service
        or UploadProtectionService(rate_limiter, concurrency_limiter, current_settings)
    )
    # 只允许本地 Vue 开发服务器跨域访问，模型密钥仍只保留在后端。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=current_settings.cors_origins,
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
    application.include_router(admin_telemetry_router, prefix="/api/v1")
    application.include_router(admin_reviews_router, prefix="/api/v1")
    application.include_router(admin_knowledge_assets_router, prefix="/api/v1")
    application.include_router(admin_operations_router, prefix="/api/v1")
    application.include_router(super_admin_users_router, prefix="/api/v1")
    application.include_router(profile_router, prefix="/api/v1")
    application.include_router(knowledge_submissions_router, prefix="/api/v1")
    application.include_router(agent_router, prefix="/api/v1")
    application.include_router(quality_router, prefix="/api/v1")
    application.include_router(memory_router, prefix="/api/v1")
    application.include_router(knowledge_trace_router, prefix="/api/v1")
    register_exception_handlers(application)
    return application


app = create_app()
