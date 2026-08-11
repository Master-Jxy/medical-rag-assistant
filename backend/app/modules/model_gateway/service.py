"""Application service for user-owned model selection."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.model_gateway.contracts import (
    ModelCapability,
    ModelRoute,
    ModelRouteRequest,
    ModelSurface,
)
from app.modules.model_gateway.policy import StaticModelRoutePolicy
from app.modules.usage.contracts import QuotaPolicyMode, resolve_quota_policy_mode
from app.modules.usage.quota_service import QuotaApplicationService


class UserModelSelectionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.policy = StaticModelRoutePolicy.from_settings(settings)
        self.quota = QuotaApplicationService(
            session,
            default_plan_code=settings.default_quota_plan_code,
            policy_mode=resolve_quota_policy_mode(
                settings.quota_policy_mode,
                settings.quota_enforcement_enabled,
            ),
        )

    def validate_text_selection(
        self,
        *,
        user_id: str,
        user_role: str,
        surface: ModelSurface,
        model_id: str | None,
    ) -> ModelRoute:
        quota_allowed = True
        if self.quota.policy_mode is QuotaPolicyMode.ENFORCE:
            current = self.quota.current(user_id)
            quota_allowed = (
                current["remaining_tokens"] > 0
                and current["remaining_requests"] > 0
            )
        return self.policy.resolve(
            ModelRouteRequest(
                surface=surface,
                task_kind="chat",
                required_capabilities=frozenset({ModelCapability.TEXT}),
                selected_model_id=model_id,
                user_role=user_role,
                quota_allowed=quota_allowed,
            )
        ).primary
