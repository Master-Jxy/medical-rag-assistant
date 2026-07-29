"""模型用量账本持久化与聚合查询。"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.modules.usage.models import ModelUsageRecord


@dataclass(frozen=True, slots=True)
class UsageAggregate:
    input_tokens: int
    output_tokens: int
    estimated_cost_cny: Decimal
    known_model_calls: int
    unknown_model_calls: int
    no_model_calls: int
    priced_model_calls: int

    @property
    def measurement_coverage(self) -> float | None:
        measured_calls = self.known_model_calls + self.unknown_model_calls
        if measured_calls == 0:
            return None
        return round(self.known_model_calls / measured_calls, 6)

    @property
    def unpriced_model_calls(self) -> int:
        return self.known_model_calls - self.priced_model_calls


class ModelUsageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_call_id(self, call_id: str) -> ModelUsageRecord | None:
        return self.session.scalar(
            select(ModelUsageRecord).where(ModelUsageRecord.call_id == call_id)
        )

    def add(self, record: ModelUsageRecord) -> None:
        self.session.add(record)

    def aggregate(self) -> UsageAggregate:
        row = self.session.execute(
            select(
                func.coalesce(func.sum(ModelUsageRecord.input_tokens), 0),
                func.coalesce(func.sum(ModelUsageRecord.output_tokens), 0),
                func.coalesce(func.sum(ModelUsageRecord.estimated_cost_cny), 0),
                func.sum(
                    case(
                        (ModelUsageRecord.token_measurement == "actual", 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (ModelUsageRecord.token_measurement == "unknown", 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            ModelUsageRecord.token_measurement
                            == "not_applicable",
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            and_(
                                ModelUsageRecord.token_measurement == "actual",
                                ModelUsageRecord.estimated_cost_cny.is_not(None),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
        ).one()
        return UsageAggregate(
            input_tokens=int(row[0] or 0),
            output_tokens=int(row[1] or 0),
            estimated_cost_cny=Decimal(row[2] or 0),
            known_model_calls=int(row[3] or 0),
            unknown_model_calls=int(row[4] or 0),
            no_model_calls=int(row[5] or 0),
            priced_model_calls=int(row[6] or 0),
        )
