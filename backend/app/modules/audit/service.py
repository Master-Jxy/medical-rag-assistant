"""按调用者角色裁剪审计范围。"""

from sqlalchemy import func, not_, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.audit.schemas import AuditEventItem, AuditEventListResponse
from app.modules.auth.roles import UserRole

SUPER_ADMIN_ONLY_PREFIXES = ("user.", "system.")


class AuditQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_events(
        self,
        *,
        viewer_role: UserRole,
        action: str | None,
        offset: int,
        limit: int,
    ) -> AuditEventListResponse:
        statement = select(AuditEvent)
        count_statement = select(func.count()).select_from(AuditEvent)
        conditions = []
        if viewer_role is not UserRole.SUPER_ADMIN:
            conditions.extend(
                not_(AuditEvent.action.like(f"{prefix}%"))
                for prefix in SUPER_ADMIN_ONLY_PREFIXES
            )
        if action:
            conditions.append(AuditEvent.action == action)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        records = self.session.scalars(
            statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return AuditEventListResponse(
            items=[
                AuditEventItem(
                    event_id=record.id,
                    actor_user_id=record.actor_user_id,
                    action=record.action,
                    object_type=record.object_type,
                    object_id=record.object_id,
                    result=record.result,
                    request_id=record.request_id,
                    details=dict(record.details or {}),
                    created_at=record.created_at,
                )
                for record in records
            ],
            total=self.session.scalar(count_statement) or 0,
            offset=offset,
            limit=limit,
        )
