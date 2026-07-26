"""独立Agent REST、SSE与产物下载接口。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.request_context import get_request_id
from app.core.sse import format_sse
from app.db.session import get_db_session
from app.modules.agent.application import AgentApplicationService
from app.modules.agent.cancellation import AgentCancellationService
from app.modules.agent.policy import AgentPolicy
from app.modules.agent.runtime import create_agent_graph_factory
from app.modules.agent.schemas import (
    AgentRunCreate,
    AgentRunListResponse,
    AgentRunResponse,
    AgentStopResponse,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.core.config import get_settings

router = APIRouter(prefix="/agent", tags=["资料Agent"])


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
