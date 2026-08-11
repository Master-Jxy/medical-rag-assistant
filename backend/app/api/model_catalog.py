"""Authenticated real model catalog and administrator route health."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import get_current_user, require_admin
from app.modules.auth.schemas import UserResponse
from app.modules.model_gateway.contracts import ModelSurface
from app.modules.model_gateway.gateway import route_health_registry
from app.modules.model_gateway.policy import StaticModelRoutePolicy
from app.modules.model_gateway.coverage import accounting_contracts


router = APIRouter(prefix="/models", tags=["模型目录"])


class ModelOption(BaseModel):
    id: str
    label: str
    provider: str
    model_name: str | None
    enabled: bool
    status: Literal["available"]
    input_price_per_million_tokens_cny: float | None = None
    output_price_per_million_tokens_cny: float | None = None


class ModelCatalogResponse(BaseModel):
    surface: Literal["rag", "agent"]
    active_model_id: str
    options: list[ModelOption]


@router.get("", response_model=ModelCatalogResponse)
def get_model_catalog(
    surface: Literal["rag", "agent"] = Query(default="rag"),
    user: UserResponse = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ModelCatalogResponse:
    gateway_surface = ModelSurface.AGENT if surface == "agent" else ModelSurface.RAG
    routes = StaticModelRoutePolicy.from_settings(settings).public_routes(
        gateway_surface, user.role
    )
    options = [
        ModelOption(
            id=route.id,
            label=route.label,
            provider="DashScope",
            model_name=route.model_name,
            enabled=True,
            status="available",
            input_price_per_million_tokens_cny=(
                settings.agent_input_price_per_million_tokens_cny
                if surface == "agent"
                else route.input_price_per_million_tokens_cny
            ),
            output_price_per_million_tokens_cny=(
                settings.agent_output_price_per_million_tokens_cny
                if surface == "agent"
                else route.output_price_per_million_tokens_cny
            ),
        )
        for route in routes
    ]
    return ModelCatalogResponse(
        surface=surface,
        active_model_id=options[0].id if options else "qwen",
        options=options,
    )


@router.get("/routes/health")
def get_model_route_health(
    _admin: UserResponse = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    policy = StaticModelRoutePolicy.from_settings(settings)
    return {
        "routes": [
            {
                "id": route.id,
                "provider": route.provider,
                "model_name": route.model_name,
                "enabled": route.enabled,
                "capabilities": sorted(item.value for item in route.capabilities),
                "surfaces": sorted(item.value for item in route.surfaces),
            }
            for route in policy.all_routes()
        ],
        "surface_accounting": accounting_contracts(),
        "recent_events": route_health_registry.snapshot(),
    }
