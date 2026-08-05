"""Stage 24.4 OCR/Vision contracts, gates, and controlled asset storage."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import Settings
from app.core.exceptions import DocumentParseError, DocumentStoreError
from app.infrastructure.document_enrichment import (
    DisabledOcrAdapter,
    DisabledVisionDocumentAdapter,
    FakeOcrAdapter,
    FakeVisionDocumentAdapter,
)
from app.modules.knowledge.asset_storage import ControlledDocumentAssetStore
from app.modules.knowledge.enrichment import (
    DocumentEnrichmentService,
    EnrichmentResourcePolicy,
)
from app.modules.knowledge.ingestion import (
    ParseQuality,
    ParsedAsset,
    ParsedDocument,
)


def make_png_bytes(size: tuple[int, int] = (2, 2)) -> bytes:
    image = Image.new("RGB", size, "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_document(
    *,
    assets: tuple[ParsedAsset, ...] | None = None,
    metadata: dict[str, object] | None = None,
) -> ParsedDocument:
    asset = ParsedAsset(
        asset_id="image-1",
        kind="uploaded_image",
        page_no=1,
        mime_type="image/png",
        storage_ref="document-asset://submissions/sub/image.png",
        sha256="a" * 64,
        metadata={
            "byte_size": 100,
            "pixel_count": 4,
            "purpose": "document_understanding",
            **(metadata or {}),
        },
    )
    return ParsedDocument(
        document_metadata={"page_count": 1},
        elements=(),
        assets=assets if assets is not None else (asset,),
        quality=ParseQuality(status="warning", counts={"asset": 1}),
    )


def test_disabled_enrichment_marks_assets_waiting_without_calling_ports() -> None:
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=False),
        ocr=DisabledOcrAdapter(),
        vision=DisabledVisionDocumentAdapter(),
    )

    enriched = service.enrich(make_document(), user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "waiting_enrichment"
    assert enriched.quality.counts["asset"] == 1
    assert enriched.quality.status == "warning"


def test_fake_enrichment_merges_ocr_and_vision_text_with_quota() -> None:
    ocr = FakeOcrAdapter({"image-1": "OCR text"})
    vision = FakeVisionDocumentAdapter({"image-1": "figure caption"})
    quota = SimpleQuotaGate()
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=ocr,
        vision=vision,
        quota_gate=quota,
    )

    enriched = service.enrich(make_document(), user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "completed"
    assert enriched.elements[0].kind == "image_text"
    assert enriched.elements[0].text == "OCR text\nfigure caption"
    assert ocr.calls and vision.calls
    assert quota.reserved == 1
    assert quota.settled == ["reservation-1"]
    assert quota.released == []


def test_diagnostic_imagery_is_restricted_before_ports_are_called() -> None:
    ocr = FakeOcrAdapter({"image-1": "should not run"})
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=ocr,
        vision=FakeVisionDocumentAdapter(),
    )

    enriched = service.enrich(make_document(metadata={"image_type": "diagnostic CT"}))

    assert enriched.document_metadata["enrichment"]["status"] == "restricted"
    assert enriched.document_metadata["enrichment"]["reason"] == "diagnostic_image_restricted"
    assert ocr.calls == []


@pytest.mark.parametrize(
    ("asset_metadata", "expected"),
    [
        ({"byte_size": 6 * 1024 * 1024, "pixel_count": 4}, "image_byte_limit"),
        ({"byte_size": 100, "pixel_count": 9_000_000}, "image_pixel_limit"),
    ],
)
def test_resource_policy_limits_single_asset(asset_metadata, expected) -> None:
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=FakeOcrAdapter(),
        vision=FakeVisionDocumentAdapter(),
    )

    enriched = service.enrich(make_document(metadata=asset_metadata))

    assert enriched.document_metadata["enrichment"]["status"] == "limited"
    assert enriched.document_metadata["enrichment"]["reason"] == expected


def test_resource_policy_limits_total_images_and_calls() -> None:
    assets = tuple(
        ParsedAsset(
            asset_id=f"image-{index}",
            kind="uploaded_image",
            page_no=index,
            mime_type="image/png",
            storage_ref=f"document-asset://submissions/sub/{index}.png",
            sha256="a" * 64,
            metadata={"byte_size": 100, "pixel_count": 4},
        )
        for index in range(3)
    )
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(
            enabled=True,
            approved=True,
            max_images=2,
            max_calls_per_document=2,
        ),
        ocr=FakeOcrAdapter(),
        vision=FakeVisionDocumentAdapter(),
    )

    enriched = service.enrich(make_document(assets=assets))

    assert enriched.document_metadata["enrichment"]["reason"] == "image_count_limit"


def test_concurrency_limit_returns_limited_without_retry() -> None:
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True, automatic_retries=0),
        ocr=FakeOcrAdapter(),
        vision=FakeVisionDocumentAdapter(),
    )
    assert service._semaphore.acquire(blocking=False) is True
    try:
        enriched = service.enrich(make_document())
    finally:
        service._semaphore.release()

    assert enriched.document_metadata["enrichment"]["status"] == "limited"
    assert enriched.document_metadata["enrichment"]["reason"] == "concurrency_limit"


def test_port_failure_releases_quota_and_keeps_manual_review_available() -> None:
    quota = SimpleQuotaGate()
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=FailingOcrAdapter(),
        vision=FakeVisionDocumentAdapter(),
        quota_gate=quota,
    )

    enriched = service.enrich(make_document(), user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "failed"
    assert quota.released == ["reservation-1"]
    assert enriched.elements == ()


def test_policy_rejects_nonzero_automatic_retries() -> None:
    with pytest.raises(DocumentParseError):
        DocumentEnrichmentService(
            policy=EnrichmentResourcePolicy(automatic_retries=1),
            ocr=FakeOcrAdapter(),
            vision=FakeVisionDocumentAdapter(),
        )


def test_asset_store_materializes_generated_storage_ref_and_cleans(tmp_path) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    source = tmp_path / "source.png"
    source.write_bytes(make_png_bytes())
    store = ControlledDocumentAssetStore(settings)

    materialized = store.materialize_submission_assets(
        make_document(),
        submission_id="submission-1",
        source_path=source,
    )

    asset = materialized.assets[0]
    assert asset.storage_ref.startswith("document-asset://submissions/submission-1/")
    assert asset.metadata["materialized"] is True
    assert (settings.document_asset_dir / "submissions" / "submission-1").is_dir()

    store.promote_submission_assets("submission-1", "document-1")
    assert not (settings.document_asset_dir / "submissions" / "submission-1").exists()
    assert (settings.document_asset_dir / "documents" / "document-1").is_dir()

    store.cleanup_document_assets("document-1")
    assert not (settings.document_asset_dir / "documents" / "document-1").exists()


def test_asset_store_rejects_traversal_identifiers(tmp_path) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    store = ControlledDocumentAssetStore(settings)

    with pytest.raises(DocumentStoreError):
        store.cleanup_submission_assets("../escape")


class SimpleQuotaGate:
    def __init__(self) -> None:
        self.reserved = 0
        self.settled: list[str] = []
        self.released: list[str] = []

    def reserve(self, **kwargs):
        self.reserved += 1
        assert kwargs["surface"] == "knowledge"
        return SimpleNamespace(id="reservation-1")

    def settle(self, reservation_id, usage):
        del usage
        self.settled.append(reservation_id)
        return None

    def release(self, reservation_id):
        self.released.append(reservation_id)
        return None


class FailingOcrAdapter:
    def extract_text(self, request):
        del request
        raise DocumentParseError("provider unavailable")
