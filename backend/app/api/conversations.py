"""会话创建、列表、详情、改名和删除接口。"""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.core.exceptions import AppError, RagServiceError
from app.core.sse import format_sse
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.schemas.chat import ChatRequest
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDeleteResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    ConversationStopResponse,
    ConversationChatResponse,
    ConversationUpdate,
)
from app.services.conversation_service import ConversationService
from app.services.conversation_chat_service import ConversationChatService
from app.services.chat_rate_limit_service import (
    ChatRateLimitService,
    get_chat_rate_limit_service,
)
from app.services.generation_lock_service import (
    GenerationLockService,
    get_generation_lock_service,
)
from app.services.idempotency_service import (
    IdempotencyService,
    get_idempotency_service,
)
from app.services.rag_service import RagService, get_rag_service
from app.services.stream_cancellation_service import (
    StreamCancellationService,
    get_stream_cancellation_service,
)

router = APIRouter(prefix="/conversations", tags=["历史会话"])

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="客户端为一次问答生成的稳定请求标识",
    ),
]


@router.post("", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreate,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationSummary:
    return ConversationService(session).create(current_user.id, request.title)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationListResponse:
    return ConversationService(session).list(current_user.id, limit, offset)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationDetail:
    return ConversationService(session).get_detail(current_user.id, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def update_conversation(
    conversation_id: str,
    request: ConversationUpdate,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationSummary:
    return ConversationService(session).update_title(
        current_user.id, conversation_id, request.title
    )


@router.delete("/{conversation_id}", response_model=ConversationDeleteResponse)
def delete_conversation(
    conversation_id: str,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationDeleteResponse:
    return ConversationService(session).delete(current_user.id, conversation_id)


@router.post("/{conversation_id}/chat", response_model=ConversationChatResponse)
def chat_in_conversation(
    conversation_id: str,
    request: ChatRequest,
    idempotency_key: IdempotencyKey,
    current_user: UserResponse = Depends(get_current_user),
    rate_limiter: ChatRateLimitService = Depends(get_chat_rate_limit_service),
    generation_lock: GenerationLockService = Depends(get_generation_lock_service),
    idempotency: IdempotencyService = Depends(get_idempotency_service),
    session: Session = Depends(get_db_session),
    rag_service: RagService = Depends(get_rag_service),
) -> ConversationChatResponse:
    """保存用户问题和助手回答，具体事务由服务层负责。"""
    rate_limiter.check(current_user.id)
    return ConversationChatService(
        session, rag_service, generation_lock, idempotency
    ).ask(
        current_user.id,
        conversation_id,
        request.question,
        request.top_k,
        idempotency_key,
    )


@router.post(
    "/{conversation_id}/chat/stop",
    response_model=ConversationStopResponse,
    summary="请求停止当前流式回答",
)
def stop_stream_chat_in_conversation(
    conversation_id: str,
    idempotency_key: IdempotencyKey,
    current_user: UserResponse = Depends(get_current_user),
    cancellation: StreamCancellationService = Depends(
        get_stream_cancellation_service
    ),
) -> ConversationStopResponse:
    requested = cancellation.request_stop(
        current_user.id, conversation_id, idempotency_key
    )
    return ConversationStopResponse(
        status="stopping" if requested else "idle",
        message="正在停止回答" if requested else "当前没有可停止的回答",
    )


@router.post(
    "/{conversation_id}/chat/stream",
    response_class=StreamingResponse,
    summary="在指定会话中流式问答并保存历史",
)
async def stream_chat_in_conversation(
    conversation_id: str,
    request: ChatRequest,
    idempotency_key: IdempotencyKey,
    current_user: UserResponse = Depends(get_current_user),
    rate_limiter: ChatRateLimitService = Depends(get_chat_rate_limit_service),
    generation_lock: GenerationLockService = Depends(get_generation_lock_service),
    idempotency: IdempotencyService = Depends(get_idempotency_service),
    cancellation: StreamCancellationService = Depends(
        get_stream_cancellation_service
    ),
    session: Session = Depends(get_db_session),
    rag_service: RagService = Depends(get_rag_service),
) -> StreamingResponse:
    request_id = str(uuid4())
    rate_limiter.check(current_user.id)
    service_iterator = ConversationChatService(
        session, rag_service, generation_lock, idempotency, cancellation
    ).stream(
        current_user.id,
        conversation_id,
        request.question,
        request.top_k,
        request_id,
        idempotency_key,
    )

    async def event_generator():
        try:
            async for item in service_iterator:
                yield format_sse(item["event"], item["data"])
        except AppError as exc:
            yield format_sse(
                "error",
                {"code": exc.code, "message": exc.message, "request_id": request_id},
            )
        except Exception:
            exc = RagServiceError()
            yield format_sse(
                "error",
                {"code": exc.code, "message": exc.message, "request_id": request_id},
            )
        finally:
            # 客户端断开时关闭内部生成器，触发 stopped 状态落库。
            await service_iterator.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
