from dataclasses import dataclass

from app.core.enums import StrEnum


class TokenMeasurement(StrEnum):
    ACTUAL = "actual"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class QuotaPolicyMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class QuotaDecisionReason(StrEnum):
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"
    REQUEST_LIMIT_EXCEEDED = "REQUEST_LIMIT_EXCEEDED"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"
    QUOTA_POLICY_UNAVAILABLE = "QUOTA_POLICY_UNAVAILABLE"
    RESERVATION_UNDERESTIMATED = "RESERVATION_UNDERESTIMATED"


def resolve_quota_policy_mode(
    configured_mode: str | None,
    legacy_enforcement_enabled: bool,
) -> QuotaPolicyMode:
    if configured_mode is not None:
        return QuotaPolicyMode(configured_mode)
    return (
        QuotaPolicyMode.ENFORCE
        if legacy_enforcement_enabled
        else QuotaPolicyMode.OFF
    )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    measurement: TokenMeasurement
    cached_input_tokens: int | None = None
    cache_creation_tokens: int | None = None
    provider_request_id: str | None = None

    @classmethod
    def actual(cls, input_tokens: int, output_tokens: int, **kwargs):
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token计量不能为负数")
        return cls(input_tokens, output_tokens, input_tokens + output_tokens, TokenMeasurement.ACTUAL, **kwargs)

    @classmethod
    def unknown(cls):
        return cls(None, None, None, TokenMeasurement.UNKNOWN)

    @classmethod
    def not_applicable(cls):
        return cls(0, 0, 0, TokenMeasurement.NOT_APPLICABLE)

    def as_dict(self):
        result = {
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens, "measurement": self.measurement.value,
        }
        if self.cached_input_tokens is not None:
            result["cached_input_tokens"] = self.cached_input_tokens
        if self.cache_creation_tokens is not None:
            result["cache_creation_tokens"] = self.cache_creation_tokens
        return result
