"""Authenticated model catalog for chat controls and pricing transparency."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse


router = APIRouter(prefix="/models", tags=["模型目录"])


class ModelOption(BaseModel):
    id: str
    label: str
    provider: str
    model_name: str | None
    enabled: bool
    status: Literal["available", "testing"]
    input_price_per_million_tokens_cny: float | None = None
    output_price_per_million_tokens_cny: float | None = None


class ModelCatalogResponse(BaseModel):
    surface: Literal["rag", "agent"]
    active_model_id: str
    options: list[ModelOption]


@router.get("", response_model=ModelCatalogResponse)
def get_model_catalog(
    surface: Literal["rag", "agent"] = Query(default="rag"),
    _user: UserResponse = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ModelCatalogResponse:
    if surface == "agent":
        input_price = settings.agent_input_price_per_million_tokens_cny
        output_price = settings.agent_output_price_per_million_tokens_cny
    else:
        input_price = settings.chat_input_price_per_million_tokens_cny
        output_price = settings.chat_output_price_per_million_tokens_cny

    return ModelCatalogResponse(
        surface=surface,
        active_model_id="qwen",
        options=[
            ModelOption(
                id="qwen",
                label="通义千问",
                provider="DashScope",
                model_name=settings.chat_model_name,
                enabled=True,
                status="available",
                input_price_per_million_tokens_cny=input_price,
                output_price_per_million_tokens_cny=output_price,
            ),
            ModelOption(
                id="deepseek",
                label="DeepSeek",
                provider="DeepSeek",
                model_name=None,
                enabled=False,
                status="testing",
            ),
            ModelOption(
                id="kimi",
                label="Kimi",
                provider="Moonshot AI",
                model_name=None,
                enabled=False,
                status="testing",
            ),
        ],
    )
