"""普通与 SSE 流式 RAG 问答接口。"""

from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.exceptions import AppError, RagServiceError
from app.core.sse import format_sse
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse
from app.services.rag_service import RagService, get_rag_service

router = APIRouter(tags=["知识库问答"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={503: {"model": ErrorResponse, "description": "模型或问答服务不可用"}},
    summary="根据知识库回答问题",
)
def chat(
    request: ChatRequest,
    rag_service: RagService = Depends(get_rag_service),
) -> ChatResponse:
    """把已校验的问题交给 RAG 服务，不在路由中编写检索和模型逻辑。"""
    request_id = str(uuid4())
    answer, sources = rag_service.ask(request.question, request.top_k)
    return ChatResponse(answer=answer, sources=sources, request_id=request_id)


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    summary="以 SSE 方式逐块返回知识库回答",
)
def stream_chat(
    request: ChatRequest,
    rag_service: RagService = Depends(get_rag_service),
) -> StreamingResponse:
    """路由只负责把服务层事件转换为 SSE，不编写检索和模型逻辑。"""
    request_id = str(uuid4())

    def event_generator():
        try:
            for item in rag_service.stream_ask(request.question, request.top_k):
                yield format_sse(item["event"], item["data"])
            yield format_sse(
                "done",
                {
                    "request_id": request_id,
                    "disclaimer": "仅供学习和信息检索，不构成医疗建议。",
                },
            )
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

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
