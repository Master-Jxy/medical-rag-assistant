from datetime import datetime, timezone

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.request_context import get_request_id
from app.modules.audit.ports import AuditRecord
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.auth.models import User
from app.modules.usage.models import (
    ModelUsageRecord, QuotaPeriod, QuotaPlan, UserQuotaAssignment,
)
from app.modules.usage.schemas import QuotaAdjustmentRequest


class QuotaTargetNotFoundError(AppError):
    def __init__(self):
        super().__init__("未找到目标用户或额度计划", code="QUOTA_TARGET_NOT_FOUND", status_code=404)


class UsageAdminService:
    def __init__(self, session: Session):
        self.session = session
        self.audit = SqlAlchemyAuditRecorder(session)

    def users(self, *, offset: int, limit: int) -> dict:
        total = self.session.scalar(select(func.count()).select_from(User)) or 0
        users = self.session.scalars(select(User)).all()
        items = []
        for user in users:
            period = self.session.scalar(select(QuotaPeriod).where(
                QuotaPeriod.user_id == user.id,
                QuotaPeriod.period_end > datetime.now(timezone.utc),
            ).order_by(QuotaPeriod.period_end.desc()))
            usage = self.session.execute(select(
                func.coalesce(func.sum(ModelUsageRecord.total_tokens), 0),
                func.count(ModelUsageRecord.id),
                func.sum(
                    (ModelUsageRecord.token_measurement == "unknown").cast(Integer)
                ),
                func.sum((ModelUsageRecord.status == "failed").cast(Integer)),
            ).where(ModelUsageRecord.user_id == user.id)).one()
            items.append({
                "user_id": user.id, "email": user.email, "role": user.role,
                "total_tokens": int(usage[0] or 0), "requests": int(usage[1] or 0),
                "unknown_calls": int(usage[2] or 0),
                "failed_calls": int(usage[3] or 0),
                "token_limit": period.token_limit if period else None,
                "used_tokens": period.used_tokens if period else 0,
                "reserved_tokens": period.reserved_tokens if period else 0,
                "remaining_tokens": max(0, period.token_limit - period.used_tokens - period.reserved_tokens) if period else None,
                "quota_exhausted": bool(period and period.used_tokens + period.reserved_tokens >= period.token_limit),
            })
        items.sort(
            key=lambda item: (
                item["total_tokens"],
                item["unknown_calls"] + item["failed_calls"],
            ),
            reverse=True,
        )
        return {
            "items": items[offset:offset + limit],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def adjust(self, *, actor_user_id: str, target_user_id: str, payload: QuotaAdjustmentRequest) -> dict:
        target = self.session.get(User, target_user_id)
        plan = self.session.scalar(select(QuotaPlan).where(
            QuotaPlan.code == payload.plan_code, QuotaPlan.enabled.is_(True)))
        if target is None or plan is None:
            raise QuotaTargetNotFoundError()
        assignment = self.session.get(UserQuotaAssignment, target_user_id)
        before = {
            "plan_id": assignment.plan_id if assignment else None,
            "token_limit_override": assignment.token_limit_override if assignment else None,
            "request_limit_override": assignment.request_limit_override if assignment else None,
        }
        if assignment is None:
            assignment = UserQuotaAssignment(user_id=target_user_id, plan_id=plan.id)
            self.session.add(assignment)
        assignment.plan_id = plan.id
        assignment.token_limit_override = payload.token_limit_override
        assignment.request_limit_override = payload.request_limit_override
        assignment.updated_by = actor_user_id
        period = self.session.scalar(select(QuotaPeriod).where(
            QuotaPeriod.user_id == target_user_id,
            QuotaPeriod.period_end > datetime.now(timezone.utc),
        ).with_for_update())
        token_limit = payload.token_limit_override or plan.token_limit
        request_limit = payload.request_limit_override or plan.request_limit
        if period:
            period.token_limit = token_limit
            period.request_limit = request_limit
        self.audit.record(AuditRecord(
            actor_user_id=actor_user_id,
            action="user.quota.adjust",
            object_type="user",
            object_id=target_user_id,
            request_id=get_request_id(),
            details={
                "reason": payload.reason,
                "before_plan_id": before["plan_id"],
                "before_token_limit": before["token_limit_override"],
                "before_request_limit": before["request_limit_override"],
                "after_plan_code": plan.code,
                "after_token_limit": payload.token_limit_override,
                "after_request_limit": payload.request_limit_override,
            },
        ))
        self.session.commit()
        return {
            "user_id": target_user_id, "plan_code": plan.code,
            "token_limit": token_limit, "request_limit": request_limit,
        }
