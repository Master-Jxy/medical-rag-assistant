"""No-cost fake and disabled adapters for chat OCR-mode extraction."""

from app.core.exceptions import VisionUnavailableError
from app.modules.usage.contracts import ModelUsage
from app.modules.vision.contracts import (
    VisionTextExtraction,
    VisionTextExtractionRequest,
    VisionTextExtractionResult,
)


class DisabledVisionTextExtractionAdapter:
    def extract(
        self, request: VisionTextExtractionRequest
    ) -> VisionTextExtractionResult:
        del request
        raise VisionUnavailableError("OCR-mode 尚未启用，请上传更清晰的图片")


class FakeVisionTextExtractionAdapter:
    def __init__(
        self,
        extraction: VisionTextExtraction | None = None,
        usage: ModelUsage | None = None,
    ) -> None:
        self.extraction = extraction or VisionTextExtraction(
            visible_text=["固定无隐私 OCR 文本"],
        )
        self.usage = usage or ModelUsage.actual(80, 24)
        self.calls: list[VisionTextExtractionRequest] = []

    def extract(
        self, request: VisionTextExtractionRequest
    ) -> VisionTextExtractionResult:
        self.calls.append(request)
        return VisionTextExtractionResult(
            extraction=self.extraction,
            usage=self.usage,
            model_name="fake-chat-ocr",
        )
