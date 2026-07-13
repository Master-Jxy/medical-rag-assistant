"""会话创建、列表、详情、改名和删除接口。"""

from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.core.exceptions import AppError, RagServiceError
from app.core.sse import format_sse
from app.schemas.chat import ChatRequest
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDeleteResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationSummary,
    ConversationChatResponse,
    ConversationUpdate,
)
from app.services.conversation_service import ConversationService
from app.services.conversation_chat_service import ConversationChatService
from app.services.rag_service import RagService, get_rag_service

router = APIRouter(prefix="/conversations", tags=["历史会话"])


@router.post("", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreate,
    session: Session = Depends(get_db_session),
) -> ConversationSummary:
    return ConversationService(session).create(request.title)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> ConversationListResponse:
    return ConversationService(session).list(limit, offset)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    session: Session = Depends(get_db_session),
) -> ConversationDetail:
    return ConversationService(session).get_detail(conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def update_conversation(
    conversation_id: str,
    request: ConversationUpdate,
    session: Session = Depends(get_db_session),
) -> ConversationSummary:
    return ConversationService(session).update_title(conversation_id, request.title)


@router.delete("/{conversation_id}", response_model=ConversationDeleteResponse)
def delete_conversation(
    conversation_id: str,
    session: Session = Depends(get_db_session),
) -> ConversationDeleteResponse:
    return ConversationService(session).delete(conversation_id)


@router.post("/{conversation_id}/chat", response_model=ConversationChatResponse)
def chat_in_conversation(
    conversation_id: str,
    request: ChatRequest,
    session: Session = Depends(get_db_session),
    rag_service: RagService = Depends(get_rag_service),
) -> ConversationChatResponse:
    """保存用户问题和助手回答，具体事务由服务层负责。"""
    return ConversationChatService(session, rag_service).ask(
        conversation_id,
        request.question,
        request.top_k,
    )


@router.post(
    "/{conversation_id}/chat/stream",
    response_class=StreamingResponse,
    summary="在指定会话中流式问答并保存历史",
)
def stream_chat_in_conversation(
    conversation_id: str,
    request: ChatRequest,
    session: Session = Depends(get_db_session),
    rag_service: RagService = Depends(get_rag_service),
) -> StreamingResponse:
    request_id = str(uuid4())
    service_iterator = ConversationChatService(session, rag_service).stream(
        conversation_id,
        request.question,
        request.top_k,
        request_id,
    )

    def event_generator():
        try:
            for item in service_iterator:
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
            service_iterator.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
