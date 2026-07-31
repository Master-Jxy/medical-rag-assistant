from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.usage.contracts import (
    ModelUsage,
    QuotaDecisionReason,
    QuotaPolicyMode,
    TokenMeasurement,
    resolve_quota_policy_mode,
)
from app.modules.usage.models import (
    QuotaPeriod,
    QuotaPlan,
    QuotaPolicyEvent,
    QuotaReservation,
    UserQuotaAssignment,
)
from app.modules.usage.query_service import UsageQueryService


class QuotaExceededError(AppError):
    def __init__(self):
        super().__init__("本周期额度不足", code="QUOTA_EXCEEDED", status_code=429)


class QuotaPolicyUnavailableError(AppError):
    def __init__(self):
        super().__init__(
            "额度费用策略暂时无法可靠计算",
            code="QUOTA_POLICY_UNAVAILABLE",
            status_code=503,
        )


class QuotaGatePort(Protocol):
    def reserve(self, user_id: str, surface: str, idempotency_key: str, requested_tokens: int,
                usage_group_id: str, **kwargs) -> QuotaReservation | None: ...
    def settle(self, reservation_id: str, usage: ModelUsage) -> QuotaReservation: ...
    def release(self, reservation_id: str) -> QuotaReservation: ...


class QuotaApplicationService:
    def __init__(
        self,
        session: Session,
        *,
        default_plan_code: str = "free",
        policy_mode: QuotaPolicyMode = QuotaPolicyMode.ENFORCE,
    ):
        self.session = session
        self.default_plan_code = default_plan_code
        self.policy_mode = policy_mode

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
            plan = self.session.scalar(select(QuotaPlan).where(
                QuotaPlan.code == self.default_plan_code,
                QuotaPlan.enabled.is_(True),
            ))
        token_limit, request_limit, cost_limit = (
            (plan.token_limit, plan.request_limit, plan.estimated_cost_limit_cny)
            if plan
            else (1_000_000, 500, None)
        )
        if assignment:
            if assignment.token_limit_override is not None:
                token_limit = assignment.token_limit_override
            if assignment.request_limit_override is not None:
                request_limit = assignment.request_limit_override
            if assignment.estimated_cost_limit_cny_override is not None:
                cost_limit = assignment.estimated_cost_limit_cny_override
        period = QuotaPeriod(user_id=user_id, period_start=start, period_end=end,
                             token_limit=token_limit, request_limit=request_limit,
                             estimated_cost_limit_cny=cost_limit)
        self.session.add(period); self.session.flush()
        return period

    def reserve(self, user_id: str, surface: str, idempotency_key: str, requested_tokens: int,
                usage_group_id: str | None = None, *,
                estimated_input_tokens: int | None = None,
                estimated_output_tokens: int | None = None,
                input_price_per_million_tokens_cny: float | None = None,
                output_price_per_million_tokens_cny: float | None = None) -> QuotaReservation:
        self.reconcile_expired(user_id=user_id, limit=20)
        existing = self.session.scalar(select(QuotaReservation).where(
            QuotaReservation.idempotency_key == idempotency_key))
        if existing:
            if existing.user_id != user_id:
                raise QuotaExceededError()
            return existing
        existing_event = self.session.scalar(select(QuotaPolicyEvent).where(
            QuotaPolicyEvent.idempotency_key == idempotency_key
        ))
        if existing_event and existing_event.would_block:
            if self.policy_mode is QuotaPolicyMode.ENFORCE:
                if (
                    existing_event.reason_code
                    == QuotaDecisionReason.QUOTA_POLICY_UNAVAILABLE.value
                ):
                    raise QuotaPolicyUnavailableError()
                raise QuotaExceededError()
        period = self._period(user_id, lock=True)
        existing = self.session.scalar(select(QuotaReservation).where(
            QuotaReservation.idempotency_key == idempotency_key))
        if existing:
            if existing.user_id != user_id:
                self.session.rollback()
                raise QuotaExceededError()
            self.session.commit()
            return existing
        remaining_tokens = max(
            0,
            period.token_limit - period.used_tokens - period.reserved_tokens,
        )
        remaining_requests = max(
            0,
            period.request_limit - period.used_requests - period.reserved_requests,
        )
        input_price = self._decimal(input_price_per_million_tokens_cny)
        output_price = self._decimal(output_price_per_million_tokens_cny)
        requested_cost = self._estimate_cost(
            estimated_input_tokens,
            estimated_output_tokens,
            input_price,
            output_price,
        )
        remaining_cost = (
            max(
                Decimal("0"),
                Decimal(period.estimated_cost_limit_cny)
                - Decimal(period.used_estimated_cost_cny)
                - Decimal(period.reserved_estimated_cost_cny),
            )
            if period.estimated_cost_limit_cny is not None
            else None
        )
        reason = None
        if requested_tokens > remaining_tokens:
            reason = QuotaDecisionReason.TOKEN_LIMIT_EXCEEDED
        elif remaining_requests < 1:
            reason = QuotaDecisionReason.REQUEST_LIMIT_EXCEEDED
        elif period.estimated_cost_limit_cny is not None and requested_cost is None:
            reason = QuotaDecisionReason.QUOTA_POLICY_UNAVAILABLE
        elif (
            remaining_cost is not None
            and requested_cost is not None
            and requested_cost > remaining_cost
        ):
            reason = QuotaDecisionReason.COST_LIMIT_EXCEEDED
        would_block = reason is not None
        if existing_event is None:
            self.session.add(QuotaPolicyEvent(
                user_id=user_id,
                surface=surface,
                policy_mode=self.policy_mode.value,
                idempotency_key=idempotency_key,
                requested_tokens=requested_tokens,
                remaining_tokens=remaining_tokens,
                remaining_requests=remaining_requests,
                requested_estimated_cost_cny=requested_cost,
                remaining_estimated_cost_cny=remaining_cost,
                would_block=would_block,
                reason_code=reason.value if reason else None,
            ))
        if would_block and self.policy_mode is QuotaPolicyMode.ENFORCE:
            self.session.commit()
            if reason is QuotaDecisionReason.QUOTA_POLICY_UNAVAILABLE:
                raise QuotaPolicyUnavailableError()
            raise QuotaExceededError()
        reservation = QuotaReservation(
            idempotency_key=idempotency_key, user_id=user_id, quota_period_id=period.id,
            surface=surface, usage_group_id=usage_group_id or str(uuid4()),
            reserved_tokens=requested_tokens,
            reserved_input_tokens=estimated_input_tokens,
            reserved_output_tokens=estimated_output_tokens,
            input_price_snapshot=input_price,
            output_price_snapshot=output_price,
            reserved_estimated_cost_cny=requested_cost,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15))
        period.reserved_tokens += requested_tokens; period.reserved_requests += 1
        if requested_cost is not None:
            period.reserved_estimated_cost_cny += requested_cost
        self.session.add(reservation); self.session.commit()
        return reservation

    def ensure_period(self, user_id: str) -> QuotaPeriod:
        period = self._period(user_id)
        self.session.commit()
        return period

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
        charged_cost = self._settled_cost(reservation, usage)
        period.reserved_tokens -= reservation.reserved_tokens; period.reserved_requests -= 1
        if reservation.reserved_estimated_cost_cny is not None:
            period.reserved_estimated_cost_cny -= reservation.reserved_estimated_cost_cny
        period.used_tokens += charged; period.used_requests += 1 if charged or usage.measurement is not TokenMeasurement.NOT_APPLICABLE else 0
        if charged_cost is not None:
            period.used_estimated_cost_cny += charged_cost
        reservation.charged_tokens = charged
        reservation.charged_estimated_cost_cny = charged_cost
        reservation.status = "settled"
        reservation.settled_at = datetime.now(timezone.utc)
        if charged > reservation.reserved_tokens:
            self.session.add(QuotaPolicyEvent(
                user_id=reservation.user_id,
                surface=reservation.surface,
                policy_mode=self.policy_mode.value,
                idempotency_key=f"under:{reservation.id}",
                requested_tokens=charged,
                remaining_tokens=max(
                    0,
                    period.token_limit - period.used_tokens - period.reserved_tokens,
                ),
                remaining_requests=max(
                    0,
                    period.request_limit
                    - period.used_requests
                    - period.reserved_requests,
                ),
                requested_estimated_cost_cny=charged_cost,
                remaining_estimated_cost_cny=(
                    max(
                        Decimal("0"),
                        Decimal(period.estimated_cost_limit_cny)
                        - Decimal(period.used_estimated_cost_cny)
                        - Decimal(period.reserved_estimated_cost_cny),
                    )
                    if period.estimated_cost_limit_cny is not None
                    else None
                ),
                would_block=True,
                reason_code=QuotaDecisionReason.RESERVATION_UNDERESTIMATED.value,
            ))
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
        if reservation.reserved_estimated_cost_cny is not None:
            period.reserved_estimated_cost_cny -= reservation.reserved_estimated_cost_cny
        reservation.status, reservation.settled_at = "released", datetime.now(timezone.utc)
        self.session.commit(); return reservation

    def current(self, user_id: str) -> dict:
        period = self._period(user_id); self.session.commit()
        consumed_tokens = period.used_tokens + period.reserved_tokens
        ratio = consumed_tokens / period.token_limit if period.token_limit else 1
        warning_level = (
            "exhausted"
            if consumed_tokens >= period.token_limit
            else "critical"
            if ratio >= 0.95
            else "warning"
            if ratio >= 0.8
            else "normal"
        )
        recent_charges = list(self.session.scalars(
            select(QuotaReservation.charged_tokens)
            .where(
                QuotaReservation.user_id == user_id,
                QuotaReservation.quota_period_id == period.id,
                QuotaReservation.status == "settled",
                QuotaReservation.charged_tokens > 0,
            )
            .order_by(QuotaReservation.settled_at.desc())
            .limit(10)
        ))
        remaining_tokens = max(
            0,
            period.token_limit - period.used_tokens - period.reserved_tokens,
        )
        remaining_requests = max(
            0,
            period.request_limit
            - period.used_requests
            - period.reserved_requests,
        )
        estimated_remaining_requests = None
        if len(recent_charges) >= 3:
            average_charge = sum(recent_charges) / len(recent_charges)
            estimated_remaining_requests = min(
                remaining_requests,
                int(remaining_tokens // average_charge),
            )
        return {
            "token_limit": period.token_limit, "used_tokens": period.used_tokens,
            "reserved_tokens": period.reserved_tokens,
            "remaining_tokens": remaining_tokens,
            "request_limit": period.request_limit, "used_requests": period.used_requests,
            "reserved_requests": period.reserved_requests,
            "remaining_requests": remaining_requests,
            "estimated_cost_limit_cny": (
                float(period.estimated_cost_limit_cny)
                if period.estimated_cost_limit_cny is not None
                else None
            ),
            "used_estimated_cost_cny": float(period.used_estimated_cost_cny),
            "reserved_estimated_cost_cny": float(period.reserved_estimated_cost_cny),
            "policy_mode": self.policy_mode.value,
            "warning_level": warning_level,
            "estimated_remaining_requests": estimated_remaining_requests,
            "period_end": period.period_end.isoformat(),
        }

    def metrics(self) -> dict[str, int]:
        return {
            "would_block_events": int(self.session.scalar(
                select(func.count()).select_from(QuotaPolicyEvent).where(
                    QuotaPolicyEvent.would_block.is_(True)
                )
            ) or 0),
            "reservation_underestimated_events": int(self.session.scalar(
                select(func.count()).select_from(QuotaPolicyEvent).where(
                    QuotaPolicyEvent.reason_code
                    == QuotaDecisionReason.RESERVATION_UNDERESTIMATED.value
                )
            ) or 0),
            "expired_reservations": int(self.session.scalar(
                select(func.count()).select_from(QuotaReservation).where(
                    QuotaReservation.status == "reserved",
                    QuotaReservation.expires_at <= datetime.now(timezone.utc),
                )
            ) or 0),
        }

    @staticmethod
    def _decimal(value: float | None) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    @staticmethod
    def _estimate_cost(
        input_tokens: int | None,
        output_tokens: int | None,
        input_price: Decimal | None,
        output_price: Decimal | None,
    ) -> Decimal | None:
        if (
            input_tokens is None
            or output_tokens is None
            or input_price is None
            or output_price is None
        ):
            return None
        return (
            Decimal(input_tokens) * input_price
            + Decimal(output_tokens) * output_price
        ) / Decimal("1000000")

    def _settled_cost(
        self,
        reservation: QuotaReservation,
        usage: ModelUsage,
    ) -> Decimal | None:
        if usage.measurement is TokenMeasurement.NOT_APPLICABLE:
            return Decimal("0")
        if usage.measurement is TokenMeasurement.UNKNOWN:
            return reservation.reserved_estimated_cost_cny
        return self._estimate_cost(
            usage.input_tokens,
            usage.output_tokens,
            reservation.input_price_snapshot,
            reservation.output_price_snapshot,
        )


class DisabledQuotaGate:
    def __init__(self, service: QuotaApplicationService | None = None):
        self.service = service
        self.policy_mode = QuotaPolicyMode.OFF

    def reserve(self, *args, **kwargs):
        user_id = kwargs.get("user_id") or (args[0] if args else None)
        if self.service is not None and user_id is not None:
            self.service.ensure_period(user_id)
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


def build_quota_gate(session: Session, settings) -> QuotaGatePort:
    mode = resolve_quota_policy_mode(
        settings.quota_policy_mode,
        settings.quota_enforcement_enabled,
    )
    service = QuotaApplicationService(
        session,
        default_plan_code=settings.default_quota_plan_code,
        policy_mode=mode,
    )
    return DisabledQuotaGate(service) if mode is QuotaPolicyMode.OFF else service
