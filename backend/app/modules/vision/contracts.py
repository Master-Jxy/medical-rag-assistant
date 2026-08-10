"""Vendor-neutral contracts for private chat image understanding."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from app.modules.usage.contracts import ModelUsage


class VisionMeasurement(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=50)
    reference_range: str | None = Field(default=None, max_length=120)
    flag: str | None = Field(default=None, max_length=30)


class VisionQualitySummary(BaseModel):
    route_kind: Literal["general", "document", "report"]
    quality_status: Literal["pass", "review", "retry"]
    quality_codes: list[str] = Field(default_factory=list, max_length=20)


class VisionObservation(BaseModel):
    image_type: str = Field(default="unknown", max_length=80)
    summary: str = Field(min_length=1, max_length=1000)
    visible_text: list[str] = Field(default_factory=list, max_length=100)
    measurements: list[VisionMeasurement] = Field(default_factory=list, max_length=50)
    objects: list[str] = Field(default_factory=list, max_length=50)
    spatial_notes: list[str] = Field(default_factory=list, max_length=50)
    uncertain_content: list[str] = Field(default_factory=list, max_length=30)
    safety_flags: list[str] = Field(default_factory=list, max_length=20)
    quality_summary: VisionQualitySummary | None = None

    @field_validator("visible_text", "objects", "spatial_notes", "uncertain_content", "safety_flags")
    @classmethod
    def clean_bounded_strings(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned[:500])
        return result

    def retrieval_text(self) -> str:
        abnormal = [
            " ".join(filter(None, [item.name, item.value, item.unit, item.reference_range, item.flag]))
            for item in self.measurements
            if item.flag and item.flag.lower() not in {"normal", "正常"}
        ]
        return "\n".join([self.summary, *self.visible_text[:20], *abnormal[:20]])[:4000]


class VisionResult(BaseModel):
    observation: VisionObservation
    usage: ModelUsage
    model_name: str
    provider_request_id: str | None = None

    model_config = {"arbitrary_types_allowed": True}


class VisionChatPort(Protocol):
    def observe(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        user_question: str,
        focus_instruction: str | None,
    ) -> VisionResult: ...
