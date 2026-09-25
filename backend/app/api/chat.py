"""普通与 SSE 流式 RAG 问答接口。"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, MediaConflictError, RagServiceError
from app.core.sse import format_sse
from app.core.request_context import get_request_id
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.db.session import get_db_session
from app.modules.model_gateway.contracts import ModelSurface
from app.modules.model_gateway.service import UserModelSelectionService
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse
from app.services.chat_rate_limit_service import (
    ChatRateLimitService,
    get_chat_rate_limit_service,
)
from app.services.rag_service import RagService, get_rag_service
from app.services.direct_chat_service import DirectChatApplicationService

router = APIRouter(tags=["知识库问答"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={503: {"model": ErrorResponse, "description": "模型或问答服务不可用"}},
    summary="根据知识库回答问题",
)
def chat(
    request: ChatRequest,
    current_user: UserResponse = Depends(get_current_user),
    rate_limiter: ChatRateLimitService = Depends(get_chat_rate_limit_service),
    rag_service: RagService = Depends(get_rag_service),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """把已校验的问题交给 RAG 服务，不在路由中编写检索和模型逻辑。"""
    request_id = get_request_id()
    rate_limiter.check(current_user.id)
    if request.attachment_ids:
        raise MediaConflictError("图片消息请在会话问答中发送")
    UserModelSelectionService(session, settings).validate_text_selection(
        user_id=current_user.id,
        user_role=current_user.role,
        surface=ModelSurface.RAG,
        model_id=request.model_id,
    )
    answer, sources = DirectChatApplicationService(
        session, rag_service, settings
    ).ask(
        user_id=current_user.id,
        request_id=request_id,
        question=request.question,
        top_k=request.top_k,
        model_id=request.model_id,
    )
    return ChatResponse(answer=answer, sources=sources, request_id=request_id)


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    summary="以 SSE 方式逐块返回知识库回答",
)
def stream_chat(
    request: ChatRequest,
    current_user: UserResponse = Depends(get_current_user),
    rate_limiter: ChatRateLimitService = Depends(get_chat_rate_limit_service),
    rag_service: RagService = Depends(get_rag_service),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """路由只负责把服务层事件转换为 SSE，不编写检索和模型逻辑。"""
    request_id = get_request_id()
    rate_limiter.check(current_user.id)
    if request.attachment_ids:
        raise MediaConflictError("图片消息请在会话问答中发送")
    UserModelSelectionService(session, settings).validate_text_selection(
        user_id=current_user.id,
        user_role=current_user.role,
        surface=ModelSurface.RAG,
        model_id=request.model_id,
    )

    def event_generator():
        try:
            for item in DirectChatApplicationService(
                session, rag_service, settings
            ).stream(
                user_id=current_user.id,
                request_id=request_id,
                question=request.question,
                top_k=request.top_k,
                model_id=request.model_id,
            ):
                yield format_sse(item["event"], item["data"])
            yield format_sse(
                "done",
                {
                    "request_id": request_id,
                    "disclaimer": "仅供学习和信息检索，不构成医疗建议。",
                },
            )
        except AppError as exc:
            public_exc = RagServiceError() if isinstance(exc, RagServiceError) else exc
            yield format_sse(
                "error",
                {
                    "code": public_exc.code,
                    "message": public_exc.message,
                    "request_id": request_id,
                },
            )
        except Exception:
            exc = RagServiceError()
            yield format_sse(
                "error",
                {"code": exc.code, "message": exc.message, "request_id": request_id},
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
