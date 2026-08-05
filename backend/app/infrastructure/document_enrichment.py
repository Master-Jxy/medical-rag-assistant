"""Disabled and fake OCR/vision adapters for Stage 24.4.

No real OCR, vision model, network, SDK, model download, or key access is
performed here.
"""

from __future__ import annotations

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.enrichment import (
    OcrPort,
    OcrRequest,
    OcrResult,
    VisionDocumentPort,
    VisionDocumentRequest,
    VisionDocumentResult,
)


class DisabledOcrAdapter(OcrPort):
    def extract_text(self, request: OcrRequest) -> OcrResult:
        del request
        raise DocumentParseError("OCR enrichment is disabled")


class DisabledVisionDocumentAdapter(VisionDocumentPort):
    def understand(self, request: VisionDocumentRequest) -> VisionDocumentResult:
        del request
        raise DocumentParseError("Vision document enrichment is disabled")


class FakeOcrAdapter(OcrPort):
    def __init__(self, text_by_asset_id: dict[str, str] | None = None) -> None:
        self.text_by_asset_id = text_by_asset_id or {}
        self.calls: list[OcrRequest] = []

    def extract_text(self, request: OcrRequest) -> OcrResult:
        self.calls.append(request)
        return OcrResult(text=self.text_by_asset_id.get(request.asset_id, ""))


class FakeVisionDocumentAdapter(VisionDocumentPort):
    def __init__(self, text_by_asset_id: dict[str, str] | None = None) -> None:
        self.text_by_asset_id = text_by_asset_id or {}
        self.calls: list[VisionDocumentRequest] = []

    def understand(self, request: VisionDocumentRequest) -> VisionDocumentResult:
        self.calls.append(request)
        return VisionDocumentResult(
            description=self.text_by_asset_id.get(request.asset_id, ""),
        )
