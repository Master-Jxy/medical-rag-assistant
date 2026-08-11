"""Provider-neutral model routing, fallback and health contracts."""

from app.modules.model_gateway.gateway import StaticModelGateway
from app.modules.model_gateway.policy import StaticModelRoutePolicy

__all__ = ["StaticModelGateway", "StaticModelRoutePolicy"]
