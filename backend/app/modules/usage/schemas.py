from pydantic import BaseModel, ConfigDict, Field


class QuotaAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_limit_override: int | None = Field(default=None, ge=1, le=2_000_000_000)
    request_limit_override: int | None = Field(default=None, ge=1, le=2_000_000_000)
    estimated_cost_limit_cny_override: float | None = Field(
        default=None,
        gt=0,
        le=1_000_000,
    )
    reason: str = Field(min_length=3, max_length=200)


class UsageFilterParams(BaseModel):
    user_id: str | None = None
    model_name: str | None = None
    surface: str | None = None
    status: str | None = None
