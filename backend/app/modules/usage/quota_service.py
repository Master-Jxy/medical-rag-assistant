from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.usage.contracts import ModelUsage, TokenMeasurement
from app.modules.usage.models import (
    QuotaPeriod, QuotaPlan, QuotaReservation, UserQuotaAssignment,
)
from app.modules.usage.query_service import UsageQueryService


class QuotaExceededError(AppError):
    def __init__(self):
        super().__init__("本周期额度不足", code="QUOTA_EXCEEDED", status_code=429)


class QuotaGatePort(Protocol):
    def reserve(self, user_id: str, surface: str, idempotency_key: str, requested_tokens: int,
                usage_group_id: str) -> QuotaReservation: ...
    def settle(self, reservation_id: str, usage: ModelUsage) -> QuotaReservation: ...
    def release(self, reservation_id: str) -> QuotaReservation: ...


class QuotaApplicationService:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _range(now: datetime) -> tuple[datetime, datetime]:
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        end = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
        return start, end

    def _period(self, user_id: str, lock: bool = False) -> QuotaPeriod:
        now = datetime.now(timezone.utc); start, end = self._range(now)
        if lock:
            self.session.scalar(
                select(User.id).where(User.id == user_id).with_for_update()
            )
        query = select(QuotaPeriod).where(
            QuotaPeriod.user_id == user_id, QuotaPeriod.period_start == start, QuotaPeriod.period_end == end)
        if lock:
            query = query.with_for_update()
        period = self.session.scalar(query)
        if period:
            return period
        assignment = self.session.get(UserQuotaAssignment, user_id)
        plan = self.session.get(QuotaPlan, assignment.plan_id) if assignment else None
        if plan is None or not plan.enabled:
            plan = self.session.scalar(select(QuotaPlan).where(QuotaPlan.code == "free", QuotaPlan.enabled.is_(True)))
        token_limit, request_limit = (plan.token_limit, plan.request_limit) if plan else (100000, 500)
        if assignment:
            token_limit = assignment.token_limit_override or token_limit
            request_limit = assignment.request_limit_override or request_limit
        period = QuotaPeriod(user_id=user_id, period_start=start, period_end=end,
                             token_limit=token_limit, request_limit=request_limit)
        self.session.add(period); self.session.flush()
        return period

    def reserve(self, user_id: str, surface: str, idempotency_key: str, requested_tokens: int,
                usage_group_id: str | None = None) -> QuotaReservation:
        self.reconcile_expired(user_id=user_id, limit=20)
        existing = self.session.scalar(select(QuotaReservation).where(
            QuotaReservation.idempotency_key == idempotency_key))
        if existing:
            if existing.user_id != user_id:
                raise QuotaExceededError()
            return existing
        period = self._period(user_id, lock=True)
        existing = self.session.scalar(select(QuotaReservation).where(
            QuotaReservation.idempotency_key == idempotency_key))
        if existing:
            if existing.user_id != user_id:
                self.session.rollback()
                raise QuotaExceededError()
            self.session.commit()
            return existing
        if period.used_tokens + period.reserved_tokens + requested_tokens > period.token_limit:
            self.session.rollback(); raise QuotaExceededError()
        if period.used_requests + period.reserved_requests + 1 > period.request_limit:
            self.session.rollback(); raise QuotaExceededError()
        reservation = QuotaReservation(
            idempotency_key=idempotency_key, user_id=user_id, quota_period_id=period.id,
            surface=surface, usage_group_id=usage_group_id or str(uuid4()),
            reserved_tokens=requested_tokens, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15))
        period.reserved_tokens += requested_tokens; period.reserved_requests += 1
        self.session.add(reservation); self.session.commit()
        return reservation

    def settle(self, reservation_id: str, usage: ModelUsage) -> QuotaReservation:
        reservation = self.session.scalar(select(QuotaReservation).where(
            QuotaReservation.id == reservation_id).with_for_update())
        if reservation is None:
            raise ValueError("quota reservation not found")
        if reservation.status != "reserved":
            return reservation
        period = self.session.scalar(select(QuotaPeriod).where(
            QuotaPeriod.id == reservation.quota_period_id).with_for_update())
        charged = reservation.reserved_tokens if usage.measurement is TokenMeasurement.UNKNOWN else int(usage.total_tokens or 0)
        period.reserved_tokens -= reservation.reserved_tokens; period.reserved_requests -= 1
        period.used_tokens += charged; period.used_requests += 1 if charged or usage.measurement is not TokenMeasurement.NOT_APPLICABLE else 0
        reservation.charged_tokens, reservation.status = charged, "settled"
        reservation.settled_at = datetime.now(timezone.utc)
        self.session.commit(); return reservation

    def reconcile_expired(
        self,
        *,
        user_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, int]:
        conditions = [
            QuotaReservation.status == "reserved",
            QuotaReservation.expires_at <= datetime.now(timezone.utc),
        ]
        if user_id is not None:
            conditions.append(QuotaReservation.user_id == user_id)
        reservation_ids = list(self.session.scalars(
            select(QuotaReservation.id)
            .where(*conditions)
            .order_by(QuotaReservation.expires_at)
            .limit(limit)
        ))
        settled = released = 0
        usage_query = UsageQueryService(self.session)
        for reservation_id in reservation_ids:
            reservation = self.session.get(QuotaReservation, reservation_id)
            if reservation is None or reservation.status != "reserved":
                continue
            summary = usage_query.group_summary(
                reservation.usage_group_id,
                reservation.user_id,
            )
            if summary is None:
                self.release(reservation.id)
                released += 1
            else:
                self.settle(
                    reservation.id,
                    usage_query.group_usage(
                        reservation.usage_group_id,
                        reservation.user_id,
                    ),
                )
                settled += 1
        return {"settled": settled, "released": released}

    def release(self, reservation_id: str) -> QuotaReservation:
        reservation = self.session.scalar(select(QuotaReservation).where(
            QuotaReservation.id == reservation_id).with_for_update())
        if reservation is None:
            raise ValueError("quota reservation not found")
        if reservation.status != "reserved":
            return reservation
        period = self.session.scalar(select(QuotaPeriod).where(
            QuotaPeriod.id == reservation.quota_period_id).with_for_update())
        period.reserved_tokens -= reservation.reserved_tokens; period.reserved_requests -= 1
        reservation.status, reservation.settled_at = "released", datetime.now(timezone.utc)
        self.session.commit(); return reservation

    def current(self, user_id: str) -> dict:
        period = self._period(user_id); self.session.commit()
        return {
            "token_limit": period.token_limit, "used_tokens": period.used_tokens,
            "reserved_tokens": period.reserved_tokens,
            "remaining_tokens": max(0, period.token_limit - period.used_tokens - period.reserved_tokens),
            "request_limit": period.request_limit, "used_requests": period.used_requests,
            "period_end": period.period_end.isoformat(),
        }


class DisabledQuotaGate:
    def reserve(self, *args, **kwargs):
        del args, kwargs
        return None

    def settle(self, reservation_id, usage):
        del reservation_id, usage
        return None

    def release(self, reservation_id):
        del reservation_id
        return None

    def current(self, user_id):
        del user_id
        return None
