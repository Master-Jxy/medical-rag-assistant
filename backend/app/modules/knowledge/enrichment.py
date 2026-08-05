"""OCR and vision enrichment contracts for document intelligence.

Stage 24.4 deliberately exposes only ports, fake/disabled adapters, and resource
gates. Real OCR or vision providers must remain outside the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import BoundedSemaphore
from typing import Mapping, Protocol
from uuid import uuid4

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.ingestion import (
    ParseQuality,
    ParsedDocument,
    ParsedElement,
)
from app.modules.usage.contracts import ModelUsage
from app.modules.usage.quota_service import QuotaGatePort


class EnrichmentStatus(str, Enum):
    DISABLED = "disabled"
    WAITING = "waiting_enrichment"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"
    LIMITED = "limited"
    RESTRICTED = "restricted"


class EnrichmentErrorCode(str, Enum):
    DISABLED = "disabled"
    NOT_APPROVED = "not_approved"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    TIMEOUT = "timeout"
    DIAGNOSTIC_IMAGE_RESTRICTED = "diagnostic_image_restricted"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True, slots=True)
class OcrRequest:
    asset_id: str
    storage_ref: str
    page_no: int | None
    mime_type: str
    timeout_seconds: float
    language_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    confidence: float | None = None
    usage: ModelUsage = field(default_factory=ModelUsage.not_applicable)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VisionDocumentRequest:
    asset_id: str
    storage_ref: str
    page_no: int | None
    mime_type: str
    purpose: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class VisionDocumentResult:
    description: str
    extracted_text: str = ""
    confidence: float | None = None
    usage: ModelUsage = field(default_factory=ModelUsage.not_applicable)
    warnings: tuple[str, ...] = ()


class OcrPort(Protocol):
    def extract_text(self, request: OcrRequest) -> OcrResult: ...


class VisionDocumentPort(Protocol):
    def understand(self, request: VisionDocumentRequest) -> VisionDocumentResult: ...


@dataclass(frozen=True, slots=True)
class EnrichmentResourcePolicy:
    enabled: bool = False
    approved: bool = False
    max_pages: int = 5
    max_images: int = 8
    max_image_bytes: int = 5 * 1024 * 1024
    max_total_image_bytes: int = 10 * 1024 * 1024
    max_pixels_per_image: int = 8_000_000
    max_total_pixels: int = 16_000_000
    max_calls_per_document: int = 4
    timeout_seconds: float = 10.0
    estimated_tokens_per_call: int = 1200
    max_concurrent: int = 1
    automatic_retries: int = 0

    def validate(self) -> None:
        if self.automatic_retries != 0:
            raise DocumentParseError("OCR/Vision automatic retries must be zero")
        for value, message in (
            (self.max_pages, "OCR/Vision page limit is invalid"),
            (self.max_images, "OCR/Vision image limit is invalid"),
            (self.max_calls_per_document, "OCR/Vision call limit is invalid"),
            (self.max_concurrent, "OCR/Vision concurrency limit is invalid"),
        ):
            if value < 0:
                raise DocumentParseError(message)

    @classmethod
    def from_settings(cls, settings) -> "EnrichmentResourcePolicy":
        return cls(
            enabled=settings.document_enrichment_enabled,
            approved=settings.document_enrichment_approved,
            max_pages=settings.document_enrichment_max_pages,
            max_images=settings.document_enrichment_max_images,
            max_image_bytes=settings.document_enrichment_max_image_bytes,
            max_total_image_bytes=settings.document_enrichment_max_total_image_bytes,
            max_pixels_per_image=settings.document_enrichment_max_pixels_per_image,
            max_total_pixels=settings.document_enrichment_max_total_pixels,
            max_calls_per_document=settings.document_enrichment_max_calls_per_document,
            timeout_seconds=settings.document_enrichment_timeout_seconds,
            estimated_tokens_per_call=settings.document_enrichment_estimated_tokens_per_call,
        )


class DocumentEnrichmentService:
    def __init__(
        self,
        *,
        policy: EnrichmentResourcePolicy,
        ocr: OcrPort,
        vision: VisionDocumentPort,
        quota_gate: QuotaGatePort | None = None,
    ) -> None:
        policy.validate()
        self.policy = policy
        self.ocr = ocr
        self.vision = vision
        self.quota_gate = quota_gate
        self._semaphore = BoundedSemaphore(max(1, policy.max_concurrent))

    def enrich(self, document: ParsedDocument, *, user_id: str | None = None) -> ParsedDocument:
        assets = tuple(document.assets)
        if not assets:
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.SKIPPED,
                detail={"reason": "no_assets"},
            )
        if not self.policy.enabled:
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.WAITING,
                detail={"reason": EnrichmentErrorCode.DISABLED.value, "asset_count": len(assets)},
                warning="OCR/Vision enrichment is disabled; image assets are waiting for manual review.",
            )
        if not self.policy.approved:
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.SKIPPED,
                detail={"reason": EnrichmentErrorCode.NOT_APPROVED.value, "asset_count": len(assets)},
                warning="OCR/Vision enrichment has not been approved for this document.",
            )
        restricted = [asset for asset in assets if _is_diagnostic_asset(asset.metadata)]
        if restricted:
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.RESTRICTED,
                detail={
                    "reason": EnrichmentErrorCode.DIAGNOSTIC_IMAGE_RESTRICTED.value,
                    "asset_count": len(assets),
                },
                warning="Diagnostic imagery such as CT, X-ray, or pathology images is not auto-interpreted.",
            )
        resource_error = self._resource_error(assets)
        if resource_error:
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.LIMITED,
                detail={"reason": resource_error, "asset_count": len(assets)},
                warning="OCR/Vision enrichment skipped because resource limits were reached.",
            )
        if not self._semaphore.acquire(blocking=False):
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.LIMITED,
                detail={"reason": "concurrency_limit", "asset_count": len(assets)},
                warning="OCR/Vision enrichment skipped because the concurrency limit is full.",
            )
        try:
            return self._run_enrichment(document, user_id=user_id)
        finally:
            self._semaphore.release()

    def _run_enrichment(self, document: ParsedDocument, *, user_id: str | None) -> ParsedDocument:
        calls = min(len(document.assets), self.policy.max_calls_per_document)
        reservation = None
        if self.quota_gate is not None and user_id is not None:
            requested = calls * self.policy.estimated_tokens_per_call
            reservation = self.quota_gate.reserve(
                user_id=user_id,
                surface="knowledge",
                idempotency_key=f"enrichment:{uuid4()}",
                requested_tokens=requested,
                usage_group_id=str(uuid4()),
                estimated_input_tokens=requested,
                estimated_output_tokens=0,
            )
        new_elements = list(document.elements)
        try:
            for asset in document.assets[:calls]:
                text = self._enrich_asset(asset)
                if text.strip():
                    new_elements.append(
                        ParsedElement(
                            element_id=f"{asset.asset_id}-image-text",
                            kind="image_text",
                            text=text.strip(),
                            page_no=asset.page_no,
                            order=len(new_elements) + 1,
                            metadata={
                                "asset_id": asset.asset_id,
                                "source": "approved_document_enrichment",
                            },
                        )
                    )
            if reservation is not None and self.quota_gate is not None:
                self.quota_gate.settle(reservation.id, ModelUsage.not_applicable())
        except Exception:
            if reservation is not None and self.quota_gate is not None:
                self.quota_gate.release(reservation.id)
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.FAILED,
                detail={"reason": "port_failure", "asset_count": len(document.assets)},
                warning="OCR/Vision enrichment failed; manual review remains available.",
            )
        if not any(element.kind == "image_text" for element in new_elements):
            return _with_enrichment_quality(
                document,
                status=EnrichmentStatus.FAILED,
                detail={"reason": "empty_enrichment", "asset_count": len(document.assets)},
                warning="OCR/Vision enrichment returned no usable text.",
            )
        return _with_enrichment_quality(
            ParsedDocument(
                document_metadata=document.document_metadata,
                elements=tuple(new_elements),
                assets=document.assets,
                warnings=document.warnings,
                quality=document.quality,
            ),
            status=EnrichmentStatus.COMPLETED,
            detail={"asset_count": len(document.assets), "calls": calls},
        )

    def _enrich_asset(self, asset) -> str:
        ocr = self.ocr.extract_text(
            OcrRequest(
                asset_id=asset.asset_id,
                storage_ref=asset.storage_ref,
                page_no=asset.page_no,
                mime_type=asset.mime_type,
                timeout_seconds=self.policy.timeout_seconds,
            )
        )
        vision = self.vision.understand(
            VisionDocumentRequest(
                asset_id=asset.asset_id,
                storage_ref=asset.storage_ref,
                page_no=asset.page_no,
                mime_type=asset.mime_type,
                purpose=str(asset.metadata.get("purpose") or "document_understanding"),
                timeout_seconds=self.policy.timeout_seconds,
            )
        )
        return "\n".join(
            part
            for part in (
                ocr.text.strip(),
                vision.extracted_text.strip(),
                vision.description.strip(),
            )
            if part
        )

    def _resource_error(self, assets) -> str | None:
        if len(assets) > self.policy.max_images:
            return "image_count_limit"
        total_bytes = 0
        total_pixels = 0
        pages = {asset.page_no for asset in assets if asset.page_no is not None}
        if len(pages) > self.policy.max_pages:
            return "page_count_limit"
        for asset in assets:
            metadata = dict(asset.metadata or {})
            size = int(metadata.get("byte_size") or 0)
            pixels = int(metadata.get("pixel_count") or 0)
            if size > self.policy.max_image_bytes:
                return "image_byte_limit"
            if pixels > self.policy.max_pixels_per_image:
                return "image_pixel_limit"
            total_bytes += size
            total_pixels += pixels
        if total_bytes > self.policy.max_total_image_bytes:
            return "total_image_byte_limit"
        if total_pixels > self.policy.max_total_pixels:
            return "total_image_pixel_limit"
        if len(assets) > self.policy.max_calls_per_document:
            return "call_count_limit"
        return None


def _with_enrichment_quality(
    document: ParsedDocument,
    *,
    status: EnrichmentStatus,
    detail: Mapping[str, object],
    warning: str | None = None,
) -> ParsedDocument:
    warnings = tuple(dict.fromkeys((*document.warnings, *((warning,) if warning else ()))))
    counts = dict(document.quality.counts)
    counts.setdefault("asset", len(document.assets))
    counts["image_text"] = sum(element.kind == "image_text" for element in document.elements)
    quality = ParseQuality(
        status="warning" if warning or document.quality.status == "warning" else document.quality.status,
        counts=counts,
        page_results=document.quality.page_results,
        warnings=warnings,
        parser_name=document.quality.parser_name,
    )
    metadata = dict(document.document_metadata)
    metadata["enrichment"] = {"status": status.value, **dict(detail)}
    return ParsedDocument(
        document_metadata=metadata,
        elements=document.elements,
        assets=document.assets,
        warnings=warnings,
        quality=quality,
    )


def _is_diagnostic_asset(metadata: Mapping[str, object]) -> bool:
    text = " ".join(
        str(metadata.get(key) or "").lower()
        for key in ("file_name", "source_name", "purpose", "image_type")
    )
    markers = (
        "ct",
        "x-ray",
        "xray",
        "pathology",
        "radiology",
        "diagnostic_image",
        "diagnostic",
        "病理",
        "影像诊断",
        "放射",
    )
    return any(marker in text for marker in markers)
