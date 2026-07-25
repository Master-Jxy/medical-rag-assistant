"""SQLAlchemy审计适配器；事务由调用用例统一提交。"""

from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.audit.ports import AuditRecord


class SqlAlchemyAuditRecorder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, event: AuditRecord) -> None:
        self.session.add(
            AuditEvent(
                actor_user_id=event.actor_user_id,
                action=event.action,
                object_type=event.object_type,
                object_id=event.object_id,
                result=event.result,
                request_id=event.request_id,
                details=dict(event.details),
            )
        )
        self.session.flush()
