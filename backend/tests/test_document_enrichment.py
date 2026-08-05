"""Stage 24.4 OCR/Vision contracts, gates, and controlled asset storage."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
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
    OcrResult,
    VisionDocumentResult,
)
from app.modules.knowledge.ingestion import (
    ParseQuality,
    ParsedAsset,
    ParsedDocument,
)
from app.modules.usage.contracts import ModelUsage, TokenMeasurement


def make_png_bytes(size: tuple[int, int] = (2, 2)) -> bytes:
    image = Image.new("RGB", size, "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_asset(
    *,
    asset_id: str = "image-1",
    materialized: bool = True,
    storage_ref: str | None = None,
    sha256: str = "a" * 64,
    metadata: dict[str, object] | None = None,
) -> ParsedAsset:
    return ParsedAsset(
        asset_id=asset_id,
        kind="uploaded_image",
        page_no=1,
        mime_type="image/png",
        storage_ref=storage_ref
        or (
            f"document-asset://submissions/sub/{asset_id}.png"
            if materialized
            else f"provenance://pdf/page-1/{asset_id}"
        ),
        sha256=sha256,
        metadata={
            "byte_size": 100,
            "pixel_count": 4,
            "purpose": "document_understanding",
            "materialized": materialized,
            **(metadata or {}),
        },
    )


def make_upload_asset(data: bytes, *, metadata: dict[str, object] | None = None) -> ParsedAsset:
    with Image.open(BytesIO(data)) as image:
        width, height = image.size
    return make_asset(
        materialized=False,
        sha256=hashlib.sha256(data).hexdigest(),
        storage_ref="upload://source",
        metadata={
            "source_kind": "uploaded_image_file",
            "width": width,
            "height": height,
            "pixel_count": width * height,
            "byte_size": len(data),
            **(metadata or {}),
        },
    )


def make_document(
    *,
    assets: tuple[ParsedAsset, ...] | None = None,
    metadata: dict[str, object] | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        document_metadata={"page_count": 1},
        elements=(),
        assets=assets if assets is not None else (make_asset(metadata=metadata),),
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
    assert enriched.document_metadata["enrichment"]["calls"] == 2
    assert enriched.elements[0].kind == "image_text"
    assert enriched.elements[0].text == "OCR text\nfigure caption"
    assert len(ocr.calls) == 1
    assert len(vision.calls) == 1
    assert quota.reserved == 1
    assert quota.settled == [("reservation-1", ModelUsage.not_applicable())]
    assert quota.released == []


def test_discovered_pdf_asset_is_not_materialized_or_sent_to_ports(tmp_path) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\n%provenance-only")
    discovered = make_asset(
        materialized=False,
        storage_ref="provenance://docling/page-1/image-1",
        metadata={"source_kind": "pdf_discovered_image", "file_name": "figure.png"},
    )
    store = ControlledDocumentAssetStore(settings)

    document = store.materialize_submission_assets(
        make_document(assets=(discovered,)),
        submission_id="submission-1",
        source_path=source,
    )

    assert not (settings.document_asset_dir / "submissions" / "submission-1").exists()
    assert document.assets[0].storage_ref == "provenance://docling/page-1/image-1"
    assert document.assets[0].metadata["materialized"] is False
    assert document.assets[0].metadata["materialization_status"] == "asset_not_materialized"

    ocr = FakeOcrAdapter({"image-1": "should not run"})
    vision = FakeVisionDocumentAdapter({"image-1": "should not run"})
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=ocr,
        vision=vision,
    )
    enriched = service.enrich(document, user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "waiting_enrichment"
    assert enriched.document_metadata["enrichment"]["reason"] == "asset_not_materialized"
    assert ocr.calls == []
    assert vision.calls == []


def test_direct_png_upload_is_revalidated_before_materialization(tmp_path) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    data = make_png_bytes()
    source = tmp_path / "source.png"
    source.write_bytes(data)
    store = ControlledDocumentAssetStore(settings)

    materialized = store.materialize_submission_assets(
        make_document(assets=(make_upload_asset(data),)),
        submission_id="submission-1",
        source_path=source,
    )

    asset = materialized.assets[0]
    assert asset.storage_ref.startswith("document-asset://submissions/submission-1/")
    assert asset.storage_ref.endswith(".png")
    assert asset.sha256 == hashlib.sha256(data).hexdigest()
    assert asset.metadata["materialized"] is True
    assert (settings.document_asset_dir / "submissions" / "submission-1").is_dir()


def test_materialization_rejects_metadata_mismatch(tmp_path) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    data = make_png_bytes()
    source = tmp_path / "source.png"
    source.write_bytes(data)
    store = ControlledDocumentAssetStore(settings)

    with pytest.raises(DocumentParseError):
        store.materialize_submission_assets(
            make_document(assets=(make_upload_asset(data, metadata={"width": 999}),)),
            submission_id="submission-1",
            source_path=source,
        )


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


@pytest.mark.parametrize("file_name", ["fact-sheet.png", "document.png", "compact-guide.png"])
def test_diagnostic_detection_does_not_match_ct_substrings(file_name) -> None:
    ocr = FakeOcrAdapter({"image-1": "OCR text"})
    vision = FakeVisionDocumentAdapter({"image-1": "caption"})
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=ocr,
        vision=vision,
    )

    enriched = service.enrich(make_document(metadata={"file_name": file_name}))

    assert enriched.document_metadata["enrichment"]["status"] == "completed"
    assert len(ocr.calls) == 1
    assert len(vision.calls) == 1


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


def test_resource_policy_limits_total_images_before_calling_ports() -> None:
    assets = tuple(
        make_asset(asset_id=f"image-{index}", metadata={"byte_size": 100, "pixel_count": 4})
        for index in range(3)
    )
    ocr = FakeOcrAdapter()
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(
            enabled=True,
            approved=True,
            max_images=2,
            max_calls_per_document=10,
        ),
        ocr=ocr,
        vision=FakeVisionDocumentAdapter(),
    )

    enriched = service.enrich(make_document(assets=assets))

    assert enriched.document_metadata["enrichment"]["reason"] == "image_count_limit"
    assert ocr.calls == []


def test_call_limit_counts_each_port_operation_before_calling_ports() -> None:
    ocr = FakeOcrAdapter({"image-1": "OCR text"})
    vision = FakeVisionDocumentAdapter({"image-1": "caption"})
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(
            enabled=True,
            approved=True,
            max_calls_per_document=1,
        ),
        ocr=ocr,
        vision=vision,
    )

    enriched = service.enrich(make_document())

    assert enriched.document_metadata["enrichment"]["status"] == "limited"
    assert enriched.document_metadata["enrichment"]["reason"] == "call_count_limit"
    assert ocr.calls == []
    assert vision.calls == []


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


def test_usage_is_aggregated_and_settled_for_real_port_calls() -> None:
    quota = SimpleQuotaGate()
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=UsageOcrAdapter(ModelUsage.actual(10, 2), text="OCR text"),
        vision=UsageVisionAdapter(ModelUsage.actual(3, 4), description="caption"),
        quota_gate=quota,
    )

    enriched = service.enrich(make_document(), user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "completed"
    assert quota.released == []
    assert quota.settled == [("reservation-1", ModelUsage.actual(13, 6))]


def test_partial_port_failure_settles_usage_already_spent() -> None:
    quota = SimpleQuotaGate()
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=UsageOcrAdapter(ModelUsage.actual(10, 2), text="OCR text"),
        vision=FailingVisionAdapter(),
        quota_gate=quota,
    )

    enriched = service.enrich(make_document(), user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "failed"
    assert quota.released == []
    assert quota.settled == [("reservation-1", ModelUsage.actual(10, 2))]


def test_port_failure_releases_quota_when_no_usage_was_spent() -> None:
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
    assert quota.settled == []
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
    data = make_png_bytes()
    source = tmp_path / "source.png"
    source.write_bytes(data)
    store = ControlledDocumentAssetStore(settings)

    materialized = store.materialize_submission_assets(
        make_document(assets=(make_upload_asset(data),)),
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


@pytest.mark.parametrize(
    "bad_id",
    ["../escape", ".", "..", "", " ", " submission-1", "submission-1 ", "bad/id", "bad\\id", "bad:id", "bad\x00id"],
)
def test_asset_store_rejects_unsafe_cleanup_identifiers(tmp_path, bad_id) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    root = settings.document_asset_dir / "submissions"
    sibling = root / "sibling"
    sibling.mkdir(parents=True)
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")
    store = ControlledDocumentAssetStore(settings)

    with pytest.raises(DocumentStoreError):
        store.cleanup_submission_assets(bad_id)

    assert root.is_dir()
    assert (sibling / "keep.txt").is_file()


def test_asset_store_raises_when_recursive_cleanup_fails(tmp_path, monkeypatch) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    target = settings.document_asset_dir / "submissions" / "submission-1"
    target.mkdir(parents=True)
    store = ControlledDocumentAssetStore(settings)

    def fail_rmtree(path):
        del path
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr("app.modules.knowledge.asset_storage.shutil.rmtree", fail_rmtree)

    with pytest.raises(DocumentStoreError):
        store.cleanup_submission_assets("submission-1")


def test_asset_store_stage_rename_failure_leaves_original_assets(tmp_path, monkeypatch) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    target = settings.document_asset_dir / "submissions" / "submission-1"
    target.mkdir(parents=True)
    (target / "asset.txt").write_text("sidecar", encoding="utf-8")
    store = ControlledDocumentAssetStore(settings)
    original_replace = Path.replace

    def fail_stage_replace(self, target_path):
        if self == target:
            raise OSError("simulated stage failure")
        return original_replace(self, target_path)

    monkeypatch.setattr(Path, "replace", fail_stage_replace)

    with pytest.raises(DocumentStoreError):
        store.stage_submission_assets_for_delete("submission-1")

    assert target.is_dir()
    assert (target / "asset.txt").is_file()
    assert not list((settings.document_asset_dir / ".trash" / "submissions").glob("*"))


@pytest.mark.parametrize(
    ("marker_name", "payload"),
    [
        (
            "document-doc-1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json",
            {
                "scope": "document",
                "object_id": "doc-1",
                "tombstone": "documents/doc-1",
                "reason": "DocumentStoreError",
            },
        ),
        (
            "document-doc-1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json",
            {
                "scope": "document",
                "object_id": "doc-1",
                "tombstone": ".trash/submissions/.doc-1.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.deleting",
                "reason": "DocumentStoreError",
            },
        ),
        (
            "document-doc-1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json",
            {
                "scope": "document",
                "object_id": "doc-1",
                "tombstone": "../documents/doc-1",
                "reason": "DocumentStoreError",
            },
        ),
        (
            "document-doc-1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json",
            {
                "scope": "document",
                "object_id": "doc-1",
                "tombstone": ".trash/documents/doc-1",
                "reason": "DocumentStoreError",
            },
        ),
        (
            "document-doc-1-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.json",
            {
                "scope": "document",
                "object_id": "doc-1",
                "tombstone": ".trash/documents/.doc-1.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.deleting",
                "reason": "DocumentStoreError",
            },
        ),
    ],
)
def test_retry_pending_cleanups_rejects_malicious_markers(
    tmp_path,
    marker_name,
    payload,
) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    protected = settings.document_asset_dir / "documents" / "doc-1"
    protected.mkdir(parents=True)
    (protected / "keep.txt").write_text("keep", encoding="utf-8")
    marker_dir = settings.document_asset_dir / ".cleanup_pending"
    marker_dir.mkdir(parents=True)
    marker = marker_dir / marker_name
    marker.write_text(json.dumps(payload), encoding="utf-8")
    store = ControlledDocumentAssetStore(settings)

    assert store.retry_pending_cleanups() == 0

    assert (protected / "keep.txt").is_file()
    assert marker.exists()


def test_retry_pending_cleanups_rejects_symlink_tombstone(tmp_path) -> None:
    settings = Settings(_env_file=None, document_asset_dir=tmp_path / "assets")
    protected = settings.document_asset_dir / "documents" / "doc-1"
    protected.mkdir(parents=True)
    (protected / "keep.txt").write_text("keep", encoding="utf-8")
    tombstone = (
        settings.document_asset_dir
        / ".trash"
        / "documents"
        / ".doc-1.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.deleting"
    )
    tombstone.parent.mkdir(parents=True)
    try:
        tombstone.symlink_to(protected, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is not allowed on this platform")
    marker_dir = settings.document_asset_dir / ".cleanup_pending"
    marker_dir.mkdir(parents=True)
    marker = marker_dir / "document-doc-1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"
    marker.write_text(
        json.dumps(
            {
                "scope": "document",
                "object_id": "doc-1",
                "tombstone": ".trash/documents/.doc-1.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.deleting",
                "reason": "DocumentStoreError",
            }
        ),
        encoding="utf-8",
    )
    store = ControlledDocumentAssetStore(settings)

    assert store.retry_pending_cleanups() == 0

    assert (protected / "keep.txt").is_file()
    assert tombstone.exists()
    assert marker.exists()


class SimpleQuotaGate:
    def __init__(self) -> None:
        self.reserved = 0
        self.settled: list[tuple[str, ModelUsage]] = []
        self.released: list[str] = []

    def reserve(self, **kwargs):
        self.reserved += 1
        assert kwargs["surface"] == "knowledge"
        return SimpleNamespace(id="reservation-1")

    def settle(self, reservation_id, usage):
        self.settled.append((reservation_id, usage))
        return None

    def release(self, reservation_id):
        self.released.append(reservation_id)
        return None


class UsageOcrAdapter:
    def __init__(self, usage: ModelUsage, *, text: str) -> None:
        self.usage = usage
        self.text = text
        self.calls = []

    def extract_text(self, request):
        self.calls.append(request)
        return OcrResult(text=self.text, usage=self.usage)


class UsageVisionAdapter:
    def __init__(self, usage: ModelUsage, *, description: str) -> None:
        self.usage = usage
        self.description = description
        self.calls = []

    def understand(self, request):
        self.calls.append(request)
        return VisionDocumentResult(description=self.description, usage=self.usage)


class FailingOcrAdapter:
    def extract_text(self, request):
        del request
        raise DocumentParseError("provider unavailable")


class FailingVisionAdapter:
    def understand(self, request):
        del request
        raise DocumentParseError("provider unavailable")


def test_unknown_usage_dominates_aggregate_usage() -> None:
    quota = SimpleQuotaGate()
    service = DocumentEnrichmentService(
        policy=EnrichmentResourcePolicy(enabled=True, approved=True),
        ocr=UsageOcrAdapter(ModelUsage.actual(1, 2), text="OCR text"),
        vision=UsageVisionAdapter(ModelUsage.unknown(), description="caption"),
        quota_gate=quota,
    )

    enriched = service.enrich(make_document(), user_id="user-1")

    assert enriched.document_metadata["enrichment"]["status"] == "completed"
    assert quota.settled[0][1].measurement is TokenMeasurement.UNKNOWN
