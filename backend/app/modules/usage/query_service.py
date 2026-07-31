from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.modules.usage.models import (
    ModelUsageRecord,
    QuotaPeriod,
    QuotaPolicyEvent,
    QuotaReservation,
)
from app.modules.usage.contracts import ModelUsage


class UsageQueryService:
    def __init__(self, session: Session):
        self.session = session

    def summary(self, user_id: str | None = None, days: int = 30) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = [ModelUsageRecord.created_at >= since]
        if user_id is not None:
            conditions.append(ModelUsageRecord.user_id == user_id)
            conditions.append(ModelUsageRecord.quota_billable.is_(True))
        row = self.session.execute(select(
            func.count(ModelUsageRecord.id), func.coalesce(func.sum(ModelUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(ModelUsageRecord.output_tokens), 0),
            func.coalesce(func.sum(ModelUsageRecord.estimated_cost_cny), 0),
            func.sum(case((ModelUsageRecord.token_measurement == "unknown", 1), else_=0)),
        ).where(*conditions)).one()
        return {"requests": int(row[0] or 0), "input_tokens": int(row[1] or 0),
                "output_tokens": int(row[2] or 0), "total_tokens": int(row[1] or 0) + int(row[2] or 0),
                "estimated_cost_cny": float(Decimal(row[3] or 0)), "unknown_calls": int(row[4] or 0)}

    def admin_overview(self, days: int = 30) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        row = self.session.execute(select(
            func.count(ModelUsageRecord.id),
            func.coalesce(func.sum(ModelUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(ModelUsageRecord.output_tokens), 0),
            func.coalesce(func.sum(ModelUsageRecord.estimated_cost_cny), 0),
            func.avg(ModelUsageRecord.latency_ms),
            func.avg(ModelUsageRecord.time_to_first_token_ms),
            func.sum(case(
                (ModelUsageRecord.token_measurement == "actual", 1),
                else_=0,
            )),
            func.sum(case(
                (ModelUsageRecord.token_measurement == "unknown", 1),
                else_=0,
            )),
            func.sum(case(
                (ModelUsageRecord.status == "failed", 1),
                else_=0,
            )),
        ).where(ModelUsageRecord.created_at >= since)).one()
        requests = int(row[0] or 0)
        actual_calls = int(row[6] or 0)
        would_block_events = int(self.session.scalar(
            select(func.count()).select_from(QuotaPolicyEvent).where(
                QuotaPolicyEvent.would_block.is_(True),
                QuotaPolicyEvent.created_at >= since,
            )
        ) or 0)
        underestimated_events = int(self.session.scalar(
            select(func.count()).select_from(QuotaPolicyEvent).where(
                QuotaPolicyEvent.reason_code == "RESERVATION_UNDERESTIMATED",
                QuotaPolicyEvent.created_at >= since,
            )
        ) or 0)
        warning_periods = list(self.session.scalars(
            select(QuotaPeriod).where(QuotaPeriod.period_end > datetime.now(timezone.utc))
        ))
        return {
            "requests": requests,
            "input_tokens": int(row[1] or 0),
            "output_tokens": int(row[2] or 0),
            "total_tokens": int(row[1] or 0) + int(row[2] or 0),
            "estimated_cost_cny": float(Decimal(row[3] or 0)),
            "average_latency_ms": round(float(row[4]), 2) if row[4] is not None else None,
            "average_time_to_first_token_ms": (
                round(float(row[5]), 2) if row[5] is not None else None
            ),
            "measurement_coverage": (
                round(actual_calls / requests, 4) if requests else 0.0
            ),
            "unknown_calls": int(row[7] or 0),
            "failed_calls": int(row[8] or 0),
            "would_block_events": would_block_events,
            "reservation_underestimated_events": underestimated_events,
            "warning_users": sum(
                1 for period in warning_periods
                if period.token_limit
                and (period.used_tokens + period.reserved_tokens) / period.token_limit
                >= 0.8
            ),
        }

    def records(
        self, user_id: str | None, offset: int, limit: int, *,
        model_name: str | None = None, surface: str | None = None,
        status: str | None = None,
    ) -> dict:
        conditions = [] if user_id is None else [
            ModelUsageRecord.user_id == user_id,
            ModelUsageRecord.quota_billable.is_(True),
        ]
        if model_name:
            conditions.append(ModelUsageRecord.model_name == model_name)
        if surface:
            conditions.append(ModelUsageRecord.surface == surface)
        if status:
            conditions.append(ModelUsageRecord.status == status)
        total = self.session.scalar(select(func.count()).select_from(ModelUsageRecord).where(*conditions)) or 0
        rows = self.session.scalars(select(ModelUsageRecord).where(*conditions)
            .order_by(ModelUsageRecord.created_at.desc()).offset(offset).limit(limit)).all()
        return {"items": [{
            "id": r.id, "user_id": r.user_id, "created_at": r.created_at, "surface": r.surface, "model_name": r.model_name,
            "status": r.status, "measurement": r.token_measurement, "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens, "total_tokens": r.total_tokens,
            "charged_tokens": self._charged_tokens(
                r.usage_group_id,
                r.user_id,
                r.token_measurement,
            ),
            "estimated_cost_cny": float(r.estimated_cost_cny) if r.estimated_cost_cny is not None else None,
            "latency_ms": r.latency_ms,
        } for r in rows], "total": total, "offset": offset, "limit": limit}

    def trend(self, user_id: str | None, days: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = [ModelUsageRecord.created_at >= since]
        if user_id is not None:
            conditions.append(ModelUsageRecord.user_id == user_id)
            conditions.append(ModelUsageRecord.quota_billable.is_(True))
        day = func.date(ModelUsageRecord.created_at)
        rows = self.session.execute(select(day, func.coalesce(func.sum(ModelUsageRecord.input_tokens), 0),
            func.coalesce(func.sum(ModelUsageRecord.output_tokens), 0)).where(*conditions).group_by(day).order_by(day)).all()
        return [{"date": str(r[0]), "input_tokens": int(r[1]), "output_tokens": int(r[2])} for r in rows]

    def group_summary(self, usage_group_id: str, user_id: str | None = None) -> dict | None:
        conditions = [
            ModelUsageRecord.usage_group_id == usage_group_id,
            ModelUsageRecord.quota_billable.is_(True),
        ]
        if user_id is not None:
            conditions.append(ModelUsageRecord.user_id == user_id)
        rows = self.session.scalars(select(ModelUsageRecord).where(*conditions)).all()
        if not rows:
            return None
        if any(row.token_measurement == "unknown" for row in rows):
            return {"measurement": "unknown", "input_tokens": None, "output_tokens": None,
                    "total_tokens": None, "estimated_cost_cny": None,
                    "charged_tokens": self._charged_tokens(usage_group_id, user_id, "unknown")}
        actual = [row for row in rows if row.token_measurement == "actual"]
        if not actual:
            return {"measurement": "not_applicable", "input_tokens": 0, "output_tokens": 0,
                    "total_tokens": 0, "estimated_cost_cny": 0.0,
                    "charged_tokens": 0}
        costs = [row.estimated_cost_cny for row in actual]
        return {"measurement": "actual",
                "input_tokens": sum(row.input_tokens or 0 for row in actual),
                "output_tokens": sum(row.output_tokens or 0 for row in actual),
                "total_tokens": sum(row.total_tokens or 0 for row in actual),
                "estimated_cost_cny": float(sum(costs)) if all(cost is not None for cost in costs) else None,
                "charged_tokens": self._charged_tokens(usage_group_id, user_id, "actual")}

    def group_usage(self, usage_group_id: str, user_id: str) -> ModelUsage:
        summary = self.group_summary(usage_group_id, user_id)
        if summary is None or summary["measurement"] == "unknown":
            return ModelUsage.unknown()
        if summary["measurement"] == "not_applicable":
            return ModelUsage.not_applicable()
        return ModelUsage.actual(summary["input_tokens"], summary["output_tokens"])

    def distribution(self, user_id: str, days: int = 30) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        surface_rows = self.session.execute(select(
            ModelUsageRecord.surface,
            func.coalesce(func.sum(ModelUsageRecord.total_tokens), 0),
            func.count(ModelUsageRecord.id),
        ).where(
            ModelUsageRecord.user_id == user_id,
            ModelUsageRecord.quota_billable.is_(True),
            ModelUsageRecord.created_at >= since,
        ).group_by(ModelUsageRecord.surface).order_by(ModelUsageRecord.surface)).all()
        model_rows = self.session.execute(select(
            ModelUsageRecord.model_name,
            func.coalesce(func.sum(ModelUsageRecord.total_tokens), 0),
            func.count(ModelUsageRecord.id),
        ).where(
            ModelUsageRecord.user_id == user_id,
            ModelUsageRecord.quota_billable.is_(True),
            ModelUsageRecord.created_at >= since,
        ).group_by(ModelUsageRecord.model_name).order_by(ModelUsageRecord.model_name)).all()
        return {
            "by_surface": [{"name": row[0], "tokens": int(row[1]), "requests": int(row[2])} for row in surface_rows],
            "by_model": [{"name": row[0], "tokens": int(row[1]), "requests": int(row[2])} for row in model_rows],
        }

    def _charged_tokens(
        self,
        usage_group_id: str | None,
        user_id: str | None,
        measurement: str,
    ) -> int:
        if measurement == "not_applicable" or usage_group_id is None:
            return 0
        conditions = [
            QuotaReservation.usage_group_id == usage_group_id,
            QuotaReservation.status == "settled",
        ]
        if user_id is not None:
            conditions.append(QuotaReservation.user_id == user_id)
        charged = self.session.scalar(
            select(QuotaReservation.charged_tokens).where(*conditions)
        )
        return int(charged or 0)
