"""Static, server-owned model route policy for the first gateway release."""

from app.core.config import Settings
from app.modules.model_gateway.contracts import (
    ModelCapability,
    ModelQuotaRejectedError,
    ModelRoute,
    ModelRouteDecision,
    ModelRouteRequest,
    ModelSelectionError,
    ModelSurface,
)

_ROLE_RANK = {"user": 0, "admin": 1, "super_admin": 2, "system": 3}


class StaticModelRoutePolicy:
    def __init__(
        self,
        routes: tuple[ModelRoute, ...],
        *,
        defaults: dict[ModelSurface, str],
        fallbacks: dict[str, str] | None = None,
    ) -> None:
        self._routes = {route.id: route for route in routes}
        if len(self._routes) != len(routes):
            raise ValueError("模型路由ID不能重复")
        self._defaults = dict(defaults)
        self._fallbacks = dict(fallbacks or {})
        for route_id in (*self._defaults.values(), *self._fallbacks.keys(), *self._fallbacks.values()):
            if route_id not in self._routes:
                raise ValueError(f"模型路由不存在: {route_id}")

    @classmethod
    def from_settings(cls, settings: Settings) -> "StaticModelRoutePolicy":
        text = ModelRoute(
            id="qwen",
            label="通义千问",
            provider="dashscope",
            model_name=settings.chat_model_name,
            capabilities=frozenset({ModelCapability.TEXT, ModelCapability.STRUCTURED_OUTPUT}),
            surfaces=frozenset({ModelSurface.RAG, ModelSurface.AGENT, ModelSurface.MEMORY}),
            user_selectable=True,
            input_price_per_million_tokens_cny=settings.chat_input_price_per_million_tokens_cny,
            output_price_per_million_tokens_cny=settings.chat_output_price_per_million_tokens_cny,
        )
        vision = ModelRoute(
            id="qwen-vision",
            label="通义千问视觉",
            provider="dashscope",
            model_name=settings.vision_model,
            capabilities=frozenset({ModelCapability.TEXT, ModelCapability.VISION, ModelCapability.STRUCTURED_OUTPUT}),
            surfaces=frozenset({ModelSurface.VISION_RAG, ModelSurface.VISION_AGENT, ModelSurface.VISION_OCR, ModelSurface.KNOWLEDGE}),
            enabled=(
                settings.vision_chat_enabled
                and settings.vision_provider == "dashscope"
            ) or (
                settings.vision_ocr_mode_enabled
                and settings.vision_ocr_provider == "dashscope"
            ),
            input_price_per_million_tokens_cny=settings.vision_input_price_per_million_tokens_cny,
            output_price_per_million_tokens_cny=settings.vision_output_price_per_million_tokens_cny,
        )
        rerank = ModelRoute(
            id="qwen-rerank",
            label="通义千问重排",
            provider="dashscope",
            model_name=settings.rag_rerank_model_name,
            capabilities=frozenset({ModelCapability.RERANK}),
            surfaces=frozenset({ModelSurface.RERANK}),
            enabled=settings.rag_rerank_enabled,
            input_price_per_million_tokens_cny=settings.rag_rerank_input_price_per_million_tokens_cny,
        )
        routes = [text, vision, rerank]
        fallbacks: dict[str, str] = {}
        if settings.model_gateway_fallback_enabled and settings.chat_fallback_model_name:
            text_fallback = ModelRoute(
                id="qwen-fallback",
                label="通义千问备用路由",
                provider="dashscope",
                model_name=settings.chat_fallback_model_name,
                capabilities=text.capabilities,
                surfaces=text.surfaces,
                input_price_per_million_tokens_cny=text.input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=text.output_price_per_million_tokens_cny,
            )
            routes.append(text_fallback)
            fallbacks[text.id] = text_fallback.id
        if settings.model_gateway_fallback_enabled and settings.vision_fallback_model_name:
            vision_fallback = ModelRoute(
                id="qwen-vision-fallback",
                label="通义千问视觉备用路由",
                provider="dashscope",
                model_name=settings.vision_fallback_model_name,
                capabilities=vision.capabilities,
                surfaces=vision.surfaces,
                enabled=vision.enabled,
                input_price_per_million_tokens_cny=vision.input_price_per_million_tokens_cny,
                output_price_per_million_tokens_cny=vision.output_price_per_million_tokens_cny,
            )
            routes.append(vision_fallback)
            fallbacks[vision.id] = vision_fallback.id
        return cls(
            tuple(routes),
            defaults={
                ModelSurface.RAG: text.id,
                ModelSurface.AGENT: text.id,
                ModelSurface.MEMORY: text.id,
                ModelSurface.VISION_RAG: vision.id,
                ModelSurface.VISION_AGENT: vision.id,
                ModelSurface.VISION_OCR: vision.id,
                ModelSurface.KNOWLEDGE: vision.id,
                ModelSurface.RERANK: rerank.id,
            },
            fallbacks=fallbacks,
        )

    def resolve(self, request: ModelRouteRequest) -> ModelRouteDecision:
        if not request.quota_allowed:
            raise ModelQuotaRejectedError()
        route_id = request.selected_model_id or self._defaults.get(request.surface)
        route = self._routes.get(route_id or "")
        if route is None or not route.enabled:
            raise ModelSelectionError("所选模型当前不可用")
        if request.surface not in route.surfaces:
            raise ModelSelectionError("所选模型不支持当前功能", code="MODEL_SURFACE_UNSUPPORTED")
        if not request.required_capabilities.issubset(route.capabilities):
            raise ModelSelectionError("所选模型能力不满足当前任务", code="MODEL_CAPABILITY_UNSUPPORTED")
        if _ROLE_RANK.get(request.user_role, -1) < _ROLE_RANK.get(route.minimum_role, 99):
            raise ModelSelectionError("当前账号无权使用该模型", code="MODEL_PERMISSION_DENIED")
        fallback = self._routes.get(self._fallbacks.get(route.id, ""))
        if fallback is not None and (
            not fallback.enabled
            or request.surface not in fallback.surfaces
            or not request.required_capabilities.issubset(fallback.capabilities)
        ):
            fallback = None
        return ModelRouteDecision(primary=route, fallback=fallback)

    def public_routes(self, surface: ModelSurface, user_role: str) -> tuple[ModelRoute, ...]:
        rank = _ROLE_RANK.get(user_role, -1)
        return tuple(
            route
            for route in self._routes.values()
            if route.enabled
            and route.user_selectable
            and surface in route.surfaces
            and rank >= _ROLE_RANK.get(route.minimum_role, 99)
        )

    def all_routes(self) -> tuple[ModelRoute, ...]:
        return tuple(self._routes.values())
