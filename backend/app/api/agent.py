"""独立Agent REST、SSE与产物下载接口。"""

from urllib.parse import quote

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.request_context import get_request_id
from app.core.sse import format_sse
from app.db.session import get_db_session
from app.modules.agent.application import AgentApplicationService
from app.modules.agent.context_builder import AgentContextBuilder
from app.modules.agent.conversation_application import AgentConversationApplication
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.runtime import create_agent_graph_factory
from app.modules.agent.message_service import AgentMessageService
from app.modules.agent.repository import AgentRepository
from app.modules.agent.recovery import AgentRecoveryService
from app.modules.agent.schemas import (
    AgentRunCreate,
    AgentRunListResponse,
    AgentRunResponse,
    AgentStopResponse,
)
from app.modules.agent.thread_repository import AgentThreadRepository
from app.modules.agent.thread_schemas import (
    AgentMessageListResponse,
    AgentMessageStreamRequest,
    AgentThreadCreate,
    AgentThreadListResponse,
    AgentThreadResponse,
    AgentThreadUpdate,
)
from app.modules.agent.thread_service import AgentThreadService
from app.modules.memory.agent_context import SqlAlchemyAgentMemoryContext
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.core.config import get_settings
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

def ensure_agent_recovery(
    request: Request,
    session: Session = Depends(get_db_session),
) -> None:
    """每个后端进程首次访问Agent接口时收敛重启前的非终态记录。"""
    if request.app.state.agent_recovery_complete:
        return
    AgentRecoveryService(session).recover_interrupted()
    request.app.state.agent_recovery_complete = True


router = APIRouter(prefix="/agent", tags=["资料Agent"])

AgentIdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="客户端为一条Agent用户消息生成的稳定请求标识",
    ),
]


def get_agent_application_service(
    request: Request,
    session: Session = Depends(get_db_session),
) -> AgentApplicationService:
    settings = get_settings()
    cancellation = request.app.state.agent_cancellation_service
    return AgentApplicationService(
        session,
        policy=AgentPolicy.from_settings(settings),
        graph_factory=create_agent_graph_factory(
            session=session,
            settings=settings,
            cancellation=cancellation,
        ),
        cancellation=cancellation,
        model_name=settings.chat_model_name,
        telemetry=request.app.state.telemetry,
    )


def get_agent_conversation_application_service(
    request: Request,
    session: Session = Depends(get_db_session),
    generation_lock: GenerationLockService = Depends(
        get_generation_lock_service
    ),
    idempotency: IdempotencyService = Depends(get_idempotency_service),
) -> AgentConversationApplication:
    ensure_agent_recovery(request, session)
    settings = get_settings()
    cancellation = request.app.state.agent_cancellation_service
    return AgentConversationApplication(
        session,
        policy=AgentPolicy.from_settings(settings),
        graph_factory=create_agent_graph_factory(
            session=session,
            settings=settings,
            cancellation=cancellation,
        ),
        cancellation=cancellation,
        generation_lock=generation_lock,
        idempotency=idempotency,
        context_builder=AgentContextBuilder(
            AgentThreadRepository(session),
            AgentRepository(session),
            SqlAlchemyAgentMemoryContext(session),
            max_tokens=min(settings.agent_max_tokens, 4000),
        ),
        model_name=settings.chat_model_name,
        telemetry=request.app.state.telemetry,
    )


@router.post(
    "/threads",
    response_model=AgentThreadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_thread(
    payload: AgentThreadCreate,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AgentThreadResponse:
    return AgentThreadService(session).create(current_user.id, payload.title)


@router.get("/threads", response_model=AgentThreadListResponse)
def list_threads(
    thread_status: str | None = Query(
        default=None,
        alias="status",
        pattern=r"^(active|archived)$",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    _recovery: None = Depends(ensure_agent_recovery),
) -> AgentThreadListResponse:
    return AgentThreadListResponse(
        items=AgentThreadService(session).list(
            current_user.id,
            status=thread_status,
            offset=offset,
            limit=limit,
        ),
        offset=offset,
        limit=limit,
    )


@router.get("/threads/{thread_id}", response_model=AgentThreadResponse)
def get_thread(
    thread_id: str,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AgentThreadResponse:
    return AgentThreadService(session).get(current_user.id, thread_id)


@router.patch("/threads/{thread_id}", response_model=AgentThreadResponse)
def update_thread(
    thread_id: str,
    payload: AgentThreadUpdate,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AgentThreadResponse:
    return AgentThreadService(session).update(
        current_user.id,
        thread_id,
        title=payload.title,
        status=payload.status,
    )


@router.delete("/threads/{thread_id}")
def delete_thread(
    thread_id: str,
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> dict[str, str]:
    AgentThreadService(session).delete(current_user.id, thread_id)
    return {"status": "deleted"}


@router.get(
    "/threads/{thread_id}/messages",
    response_model=AgentMessageListResponse,
)
def list_messages(
    thread_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    _recovery: None = Depends(ensure_agent_recovery),
) -> AgentMessageListResponse:
    return AgentMessageListResponse(
        items=AgentMessageService(session).list(
            current_user.id,
            thread_id,
            offset=offset,
            limit=limit,
        ),
        offset=offset,
        limit=limit,
    )


def _conversation_stream_response(
    iterator,
    request_id: str,
) -> StreamingResponse:
    def events():
        try:
            for item in iterator:
                yield format_sse(item["event"], item["data"])
        except AppError as exc:
            yield format_sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request_id,
                },
            )
        except Exception:
            yield format_sse(
                "error",
                {
                    "code": "AGENT_CONVERSATION_FAILED",
                    "message": "Agent会话运行失败，请稍后重试",
                    "request_id": request_id,
                },
            )
        finally:
            iterator.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/threads/{thread_id}/messages/stream",
    response_class=StreamingResponse,
)
def stream_thread_message(
    thread_id: str,
    payload: AgentMessageStreamRequest,
    idempotency_key: AgentIdempotencyKey,
    current_user: UserResponse = Depends(get_current_user),
    rate_limiter: ChatRateLimitService = Depends(get_chat_rate_limit_service),
    service: AgentConversationApplication = Depends(
        get_agent_conversation_application_service
    ),
) -> StreamingResponse:
    rate_limiter.check(current_user.id)
    request_id = get_request_id()
    return _conversation_stream_response(
        service.stream_message(
            user_id=current_user.id,
            thread_id=thread_id,
            payload=payload,
            client_request_id=idempotency_key,
            request_id=request_id,
        ),
        request_id,
    )


@router.post(
    "/messages/{message_id}/retry",
    response_class=StreamingResponse,
)
def retry_thread_message(
    message_id: str,
    idempotency_key: AgentIdempotencyKey,
    current_user: UserResponse = Depends(get_current_user),
    rate_limiter: ChatRateLimitService = Depends(get_chat_rate_limit_service),
    service: AgentConversationApplication = Depends(
        get_agent_conversation_application_service
    ),
) -> StreamingResponse:
    rate_limiter.check(current_user.id)
    request_id = get_request_id()
    return _conversation_stream_response(
        service.retry_message(
            user_id=current_user.id,
            message_id=message_id,
            client_request_id=idempotency_key,
            request_id=request_id,
        ),
        request_id,
    )


@router.post("/runs", response_model=AgentRunResponse, status_code=201)
def create_run(
    payload: AgentRunCreate,
    current_user: UserResponse = Depends(get_current_user),
    service: AgentApplicationService = Depends(get_agent_application_service),
) -> AgentRunResponse:
    return service.create_run(current_user.id, payload.task)


@router.get("/runs", response_model=AgentRunListResponse)
def list_runs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
    service: AgentApplicationService = Depends(get_agent_application_service),
) -> AgentRunListResponse:
    return service.list_runs(current_user.id, offset=offset, limit=limit)


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
def get_run(
    run_id: str,
    current_user: UserResponse = Depends(get_current_user),
    service: AgentApplicationService = Depends(get_agent_application_service),
) -> AgentRunResponse:
    return service.get_run(current_user.id, run_id)


@router.post("/runs/{run_id}/stop", response_model=AgentStopResponse)
def stop_run(
    run_id: str,
    current_user: UserResponse = Depends(get_current_user),
    service: AgentApplicationService = Depends(get_agent_application_service),
) -> AgentStopResponse:
    return service.stop_run(current_user.id, run_id)


@router.post("/runs/{run_id}/stream", response_class=StreamingResponse)
def stream_run(
    run_id: str,
    current_user: UserResponse = Depends(get_current_user),
    service: AgentApplicationService = Depends(get_agent_application_service),
) -> StreamingResponse:
    request_id = get_request_id()

    def events():
        try:
            for item in service.stream_run(current_user.id, run_id):
                yield format_sse(item["event"], item["data"])
        except AppError as exc:
            yield format_sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request_id,
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    current_user: UserResponse = Depends(get_current_user),
    service: AgentApplicationService = Depends(get_agent_application_service),
) -> Response:
    artifact = service.get_artifact(current_user.id, artifact_id)
    encoded_name = quote(artifact.file_name)
    return Response(
        content=artifact.content.encode("utf-8"),
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"
        },
    )
