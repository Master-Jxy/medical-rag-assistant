"""模型usage记录服务：价格快照、幂等与脱敏聚合。"""

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.usage.contracts import ModelUsage, TokenMeasurement
from app.modules.usage.models import ModelUsageRecord
from app.modules.usage.repository import ModelUsageRepository, UsageAggregate

MILLION = Decimal("1000000")


class ModelUsageRecorder:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = ModelUsageRepository(session)

    def record(
        self,
        *,
        call_id: str,
        request_id: str | None,
        user_id: str | None,
        surface: str,
        operation: str,
        model_name: str,
        usage: ModelUsage,
        input_price_per_million_tokens_cny: float | None = None,
        output_price_per_million_tokens_cny: float | None = None,
        usage_group_id: str | None = None,
        provider: str = "dashscope",
        status: str = "completed",
        latency_ms: int | None = None,
        time_to_first_token_ms: int | None = None,
        quota_billable: bool = True,
    ) -> ModelUsageRecord:
        existing = self.repository.find_by_call_id(call_id)
        if existing is not None:
            return existing

        configured_input_price = (
            self.settings.chat_input_price_per_million_tokens_cny
            if input_price_per_million_tokens_cny is None
            else input_price_per_million_tokens_cny
        )
        configured_output_price = (
            self.settings.chat_output_price_per_million_tokens_cny
            if output_price_per_million_tokens_cny is None
            else output_price_per_million_tokens_cny
        )
        input_price = self._price(configured_input_price)
        output_price = self._price(
            configured_output_price
        )
        estimated_cost = self._estimate_cost(usage, input_price, output_price)
        record = ModelUsageRecord(
            call_id=call_id,
            request_id=request_id,
            user_id=user_id,
            surface=surface,
            operation=operation,
            model_name=model_name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            token_measurement=usage.measurement.value,
            input_price_snapshot=input_price,
            output_price_snapshot=output_price,
            estimated_cost_cny=estimated_cost,
            usage_group_id=usage_group_id,
            provider=provider,
            status=status,
            latency_ms=latency_ms,
            time_to_first_token_ms=time_to_first_token_ms,
            cached_input_tokens=usage.cached_input_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            quota_billable=quota_billable,
        )
        self.repository.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.find_by_call_id(call_id)
            if concurrent is None:
                raise
            return concurrent
        return record

    def aggregate(self) -> UsageAggregate:
        return self.repository.aggregate()

    @staticmethod
    def _price(value: float | None) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    @staticmethod
    def _estimate_cost(
        usage: ModelUsage,
        input_price: Decimal | None,
        output_price: Decimal | None,
    ) -> Decimal | None:
        if usage.measurement is TokenMeasurement.NOT_APPLICABLE:
            return Decimal("0")
        if (
            usage.measurement is not TokenMeasurement.ACTUAL
            or usage.input_tokens is None
            or usage.output_tokens is None
            or input_price is None
            or output_price is None
        ):
            return None
        return (
            Decimal(usage.input_tokens) * input_price
            + Decimal(usage.output_tokens) * output_price
        ) / MILLION
