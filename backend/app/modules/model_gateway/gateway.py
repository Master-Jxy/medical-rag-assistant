"""Controlled single-fallback model gateway with bounded health telemetry."""

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Generic, TypeVar

from app.modules.model_gateway.contracts import (
    GatewayResult,
    GatewayUsageEvent,
    ModelFailureKind,
    ModelGatewayPort,
    ModelRoute,
    ModelRoutePolicy,
    ModelRouteRequest,
    ProviderCallResult,
)
from app.modules.usage.contracts import ModelUsage

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RouteHealthEvent:
    occurred_at: str
    route_id: str
    provider: str
    model_name: str
    surface: str
    status: str
    failure_kind: str | None
    fallback_route_id: str | None


class ModelRouteHealthRegistry:
    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[RouteHealthEvent] = deque(maxlen=max_events)
        self._lock = Lock()

    def record(self, route: ModelRoute, request: ModelRouteRequest, *, status: str,
               failure_kind: ModelFailureKind | None = None, fallback_route_id: str | None = None) -> None:
        event = RouteHealthEvent(
            occurred_at=datetime.now(timezone.utc).isoformat(),
            route_id=route.id,
            provider=route.provider,
            model_name=route.model_name,
            surface=request.surface.value,
            status=status,
            failure_kind=failure_kind.value if failure_kind else None,
            fallback_route_id=fallback_route_id,
        )
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [asdict(item) for item in reversed(self._events)]


route_health_registry = ModelRouteHealthRegistry()


def classify_model_failure(exc: Exception) -> ModelFailureKind:
    code = str(getattr(exc, "code", None) or getattr(exc, "provider_code", None) or "").upper()
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    if code.startswith("QUOTA_") or code == "QUOTA_EXCEEDED" or "quota" in name:
        return ModelFailureKind.QUOTA_REJECTED
    if "SAFETY" in code or "CONTENT_FILTER" in code or "POLICY_REJECTION" in code:
        return ModelFailureKind.SAFETY_REJECTION
    if isinstance(exc, (TypeError, ValueError)) or status in {400, 404, 409, 422}:
        return ModelFailureKind.INVALID_REQUEST
    if status == 429 or "RATE_LIMIT" in code or "THROTTL" in code or "ratelimit" in name:
        return ModelFailureKind.RATE_LIMITED
    if isinstance(exc, (TimeoutError, ConnectionError)) or "connecttimeout" in name or "readtimeout" in name:
        return ModelFailureKind.CONNECT_TIMEOUT
    if status in {502, 503, 504} or code in {"SERVICE_UNAVAILABLE", "INTERNAL_ERROR", "TEMPORARILY_UNAVAILABLE"}:
        return ModelFailureKind.TEMPORARY_PROVIDER
    if status is not None and 400 <= int(status) < 500:
        return ModelFailureKind.PERMANENT_PROVIDER
    return ModelFailureKind.UNKNOWN


class StaticModelGateway(ModelGatewayPort, Generic[T]):
    def __init__(self, policy: ModelRoutePolicy, *, health: ModelRouteHealthRegistry | None = None) -> None:
        self.policy = policy
        self.health = health or route_health_registry

    def resolve(self, request: ModelRouteRequest):
        return self.policy.resolve(request)

    def invoke(self, request: ModelRouteRequest, *, usage_group_id: str, call, usage_sink=None) -> GatewayResult[T]:
        decision = self.resolve(request)
        usage_events: list[GatewayUsageEvent] = []
        routes = (decision.primary,) + ((decision.fallback,) if decision.fallback else ())
        for index, route in enumerate(routes, start=1):
            try:
                result: ProviderCallResult[T] = call(route)
            except Exception as exc:
                kind = classify_model_failure(exc)
                consumed_usage = getattr(exc, "usage", None)
                if not isinstance(consumed_usage, ModelUsage):
                    consumed_usage = ModelUsage.unknown()
                event = GatewayUsageEvent(usage_group_id, index, route, consumed_usage, "failed")
                usage_events.append(event)
                if usage_sink is not None:
                    usage_sink(event)
                fallback_id = decision.fallback.id if index == 1 and decision.fallback and kind.allows_fallback else None
                self.health.record(route, request, status="failed", failure_kind=kind, fallback_route_id=fallback_id)
                if index == 1 and fallback_id is not None:
                    continue
                raise
            event = GatewayUsageEvent(usage_group_id, index, route, result.usage, "completed")
            usage_events.append(event)
            if usage_sink is not None:
                usage_sink(event)
            self.health.record(route, request, status="completed")
            return GatewayResult(result.value, route, index, tuple(usage_events))
        raise RuntimeError("模型网关未找到可执行路由")
