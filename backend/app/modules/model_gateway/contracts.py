"""Stable contracts for model selection and controlled provider fallback."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from app.core.enums import StrEnum
from app.core.exceptions import AppError
from app.modules.usage.contracts import ModelUsage

T = TypeVar("T")


class ModelCapability(StrEnum):
    TEXT = "text"
    VISION = "vision"
    RERANK = "rerank"
    STRUCTURED_OUTPUT = "structured_output"


class ModelSurface(StrEnum):
    RAG = "rag"
    AGENT = "agent"
    VISION_RAG = "vision_rag"
    VISION_AGENT = "vision_agent"
    VISION_OCR = "vision_ocr"
    RERANK = "rerank"
    MEMORY = "memory"
    KNOWLEDGE = "knowledge"


class ModelFailureKind(StrEnum):
    CONNECT_TIMEOUT = "connect_timeout"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_PROVIDER = "temporary_provider"
    SAFETY_REJECTION = "safety_rejection"
    INVALID_REQUEST = "invalid_request"
    QUOTA_REJECTED = "quota_rejected"
    PERMANENT_PROVIDER = "permanent_provider"
    UNKNOWN = "unknown"

    @property
    def allows_fallback(self) -> bool:
        return self in {
            ModelFailureKind.CONNECT_TIMEOUT,
            ModelFailureKind.RATE_LIMITED,
            ModelFailureKind.TEMPORARY_PROVIDER,
        }


@dataclass(frozen=True, slots=True)
class ModelRoute:
    id: str
    label: str
    provider: str
    model_name: str
    capabilities: frozenset[ModelCapability]
    surfaces: frozenset[ModelSurface]
    enabled: bool = True
    user_selectable: bool = False
    minimum_role: str = "user"
    input_price_per_million_tokens_cny: float | None = None
    output_price_per_million_tokens_cny: float | None = None


@dataclass(frozen=True, slots=True)
class ModelRouteRequest:
    surface: ModelSurface
    task_kind: str
    required_capabilities: frozenset[ModelCapability]
    selected_model_id: str | None = None
    user_role: str = "user"
    quota_allowed: bool = True


@dataclass(frozen=True, slots=True)
class ModelRouteDecision:
    primary: ModelRoute
    fallback: ModelRoute | None = None


@dataclass(frozen=True, slots=True)
class ProviderCallResult(Generic[T]):
    value: T
    usage: ModelUsage


@dataclass(frozen=True, slots=True)
class GatewayUsageEvent:
    usage_group_id: str
    attempt: int
    route: ModelRoute
    usage: ModelUsage
    status: str


@dataclass(frozen=True, slots=True)
class GatewayResult(Generic[T]):
    value: T
    route: ModelRoute
    attempts: int
    usage_events: tuple[GatewayUsageEvent, ...] = field(default_factory=tuple)


class ModelSelectionError(AppError):
    def __init__(self, message: str, *, code: str = "MODEL_NOT_AVAILABLE"):
        super().__init__(message, code=code, status_code=422)


class ModelQuotaRejectedError(AppError):
    def __init__(self):
        super().__init__("本周期额度不足，无法选择模型", code="QUOTA_EXCEEDED", status_code=429)


class ProviderCallConsumedError(RuntimeError):
    """Provider failed after a billable call and supplied its usage."""

    def __init__(self, message: str, *, usage: ModelUsage, provider_code: str | None = None):
        super().__init__(message)
        self.usage = usage
        self.provider_code = provider_code


class ModelRoutePolicy(Protocol):
    def resolve(self, request: ModelRouteRequest) -> ModelRouteDecision: ...
    def public_routes(self, surface: ModelSurface, user_role: str) -> tuple[ModelRoute, ...]: ...


class ModelGatewayPort(Protocol):
    def resolve(self, request: ModelRouteRequest) -> ModelRouteDecision: ...

    def invoke(
        self,
        request: ModelRouteRequest,
        *,
        usage_group_id: str,
        call: Callable[[ModelRoute], ProviderCallResult[T]],
        usage_sink: Callable[[GatewayUsageEvent], None] | None = None,
    ) -> GatewayResult[T]: ...
