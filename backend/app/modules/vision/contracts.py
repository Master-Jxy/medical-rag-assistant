"""Vendor-neutral contracts for private chat image understanding."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import VisionUnavailableError
from app.modules.usage.contracts import ModelUsage


class VisionMeasurement(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=50)
    reference_range: str | None = Field(default=None, max_length=120)
    flag: str | None = Field(default=None, max_length=30)


class VisionQualitySummary(BaseModel):
    route_kind: Literal[
        "general",
        "document",
        "report",
        "overview_only",
        "ocr_mode",
        "reupload_required",
    ]
    quality_status: Literal["pass", "review", "retry"]
    quality_codes: list[str] = Field(default_factory=list, max_length=20)


class VisionObservation(BaseModel):
    image_type: str = Field(default="unknown", max_length=80)
    summary: str = Field(min_length=1, max_length=1000)
    visible_text: list[str] = Field(default_factory=list, max_length=100)
    measurements: list[VisionMeasurement] = Field(default_factory=list, max_length=50)
    table_rows: list[list[str]] = Field(default_factory=list, max_length=100)
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
        table_text = [" | ".join(row) for row in self.table_rows[:20]]
        return "\n".join(
            [self.summary, *self.visible_text[:20], *table_text, *abnormal[:20]]
        )[:4000]


class VisionTextExtractionRequest(BaseModel):
    image_bytes: bytes
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    language_hints: tuple[str, ...] = ("zh", "en")
    extract_tables: bool = True
    max_output_chars: int = Field(default=8000, ge=1, le=20000)

    model_config = {"arbitrary_types_allowed": True}


class VisionTextExtraction(BaseModel):
    visible_text: list[str] = Field(default_factory=list, max_length=100)
    measurements: list[VisionMeasurement] = Field(default_factory=list, max_length=50)
    table_rows: list[list[str]] = Field(default_factory=list, max_length=100)
    uncertain_content: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("visible_text", "uncertain_content")
    @classmethod
    def clean_extracted_strings(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            cleaned = " ".join(str(value).strip().split())[:500]
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result

    @field_validator("table_rows")
    @classmethod
    def clean_table_rows(cls, rows: list[list[str]]) -> list[list[str]]:
        result: list[list[str]] = []
        for row in rows:
            cleaned = [" ".join(str(cell).strip().split())[:500] for cell in row]
            if any(cleaned) and cleaned not in result:
                result.append(cleaned[:30])
        return result


class VisionTextExtractionResult(BaseModel):
    extraction: VisionTextExtraction
    usage: ModelUsage
    model_name: str
    provider_request_id: str | None = None

    model_config = {"arbitrary_types_allowed": True}


class VisionTextExtractionConsumedError(VisionUnavailableError):
    """Provider returned a billable response that failed controlled parsing."""

    def __init__(
        self,
        *,
        usage: ModelUsage,
        model_name: str,
        provider_request_id: str | None,
    ) -> None:
        super().__init__("OCR-mode 返回内容无法安全解析，请重新上传清晰图片")
        self.code = "VISION_OCR_INVALID_RESPONSE"
        self.usage = usage
        self.model_name = model_name
        self.provider_request_id = provider_request_id


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


class VisionTextExtractionPort(Protocol):
    def extract(
        self, request: VisionTextExtractionRequest
    ) -> VisionTextExtractionResult: ...
