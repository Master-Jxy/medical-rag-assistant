from dataclasses import dataclass

from app.core.enums import StrEnum


class TokenMeasurement(StrEnum):
    ACTUAL = "actual"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


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
