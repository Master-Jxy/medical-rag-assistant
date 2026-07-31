from pydantic import BaseModel, ConfigDict, Field


class QuotaAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(default="free", min_length=1, max_length=32)
    token_limit_override: int | None = Field(default=None, ge=1, le=2_000_000_000)
    request_limit_override: int | None = Field(default=None, ge=1, le=2_000_000_000)
    reason: str = Field(min_length=3, max_length=200)


class UsageFilterParams(BaseModel):
    user_id: str | None = None
    model_name: str | None = None
    surface: str | None = None
    status: str | None = None
