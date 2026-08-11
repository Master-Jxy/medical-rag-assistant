"""Opt-in low-cardinality Prometheus endpoint."""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.core.config import Settings, get_settings
from app.ports.telemetry import render_prometheus

router = APIRouter(tags=["运维指标"])


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOT_FOUND")
    configured = settings.metrics_bearer_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="METRICS_TOKEN_NOT_CONFIGURED",
        )
    expected = f"Bearer {configured.get_secret_value()}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="UNAUTHORIZED")
    telemetry = getattr(request.app.state, "telemetry", None)
    snapshot = getattr(telemetry, "snapshot", None)
    if not callable(snapshot):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="METRICS_UNAVAILABLE")
    return PlainTextResponse(render_prometheus(snapshot()))
