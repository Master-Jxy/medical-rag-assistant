"""Controlled storage for materialized document image assets."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.exceptions import DocumentParseError, DocumentStoreError
from app.modules.knowledge.ingestion import ParseQuality, ParsedAsset, ParsedDocument


SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
TRUSTED_UPLOAD_SOURCE_KIND = "uploaded_image_file"
MATERIALIZED_MIME_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}


@dataclass(frozen=True, slots=True)
class StagedAssetDeletion:
    scope: str
    object_id: str
    original_dir: Path
    tombstone_dir: Path
    pending_marker: Path
    moved: bool


class ControlledDocumentAssetStore:
    """Stores image assets under server-generated paths only."""

    def __init__(self, settings: Settings) -> None:
        self.base_dir = settings.document_asset_dir

    def materialize_submission_assets(
        self,
        document: ParsedDocument,
        *,
        submission_id: str,
        source_path: Path,
    ) -> ParsedDocument:
        if not document.assets:
            return document
        target_dir = self._submission_dir(submission_id)
        assets: list[ParsedAsset] = []
        warnings = list(document.warnings)
        for asset in document.assets:
            if self._can_materialize_from_upload(asset):
                assets.append(
                    self._materialize_asset(asset, source_path, target_dir, scope="submission")
                )
            else:
                assets.append(self._mark_not_materialized(asset))
                warnings.append(
                    "Image asset is provenance-only and was not materialized for OCR/Vision."
                )
        deduped_warnings = tuple(dict.fromkeys(warnings))
        return ParsedDocument(
            document_metadata=document.document_metadata,
            elements=document.elements,
            assets=tuple(assets),
            warnings=deduped_warnings,
            quality=ParseQuality(
                status="warning" if deduped_warnings else document.quality.status,
                counts=document.quality.counts,
                page_results=document.quality.page_results,
                warnings=deduped_warnings,
                parser_name=document.quality.parser_name,
            ),
        )

    def promote_submission_assets(self, submission_id: str, document_id: str) -> None:
        source_dir = self._submission_dir(submission_id)
        if not source_dir.exists():
            return
        target_dir = self._document_dir(document_id)
        self._assert_under_base(source_dir)
        self._assert_under_base(target_dir)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            self.cleanup_document_assets(document_id)
        source_dir.replace(target_dir)

    def cleanup_submission_assets(self, submission_id: str) -> None:
        self._safe_rmtree(self._submission_dir(submission_id))

    def cleanup_document_assets(self, document_id: str) -> None:
        self._safe_rmtree(self._document_dir(document_id))

    def stage_submission_assets_for_delete(self, submission_id: str) -> StagedAssetDeletion:
        return self._stage_assets_for_delete(
            "submission",
            submission_id,
            self._submission_dir(submission_id),
        )

    def stage_document_assets_for_delete(self, document_id: str) -> StagedAssetDeletion:
        return self._stage_assets_for_delete(
            "document",
            document_id,
            self._document_dir(document_id),
        )

    def restore_staged_deletion(self, staged: StagedAssetDeletion) -> None:
        if not staged.moved:
            return
        self._assert_under_base(staged.original_dir)
        self._assert_under_base(staged.tombstone_dir)
        if not staged.tombstone_dir.exists():
            return
        if staged.original_dir.exists():
            raise DocumentStoreError()
        staged.original_dir.parent.mkdir(parents=True, exist_ok=True)
        staged.tombstone_dir.replace(staged.original_dir)
        staged.pending_marker.unlink(missing_ok=True)

    def finalize_staged_deletion(self, staged: StagedAssetDeletion) -> None:
        if not staged.moved:
            staged.pending_marker.unlink(missing_ok=True)
            return
        self._safe_rmtree(staged.tombstone_dir)
        staged.pending_marker.unlink(missing_ok=True)

    def mark_cleanup_pending(
        self,
        staged: StagedAssetDeletion,
        *,
        reason: str,
    ) -> None:
        if not staged.moved:
            return
        self._assert_under_base(staged.tombstone_dir)
        marker_dir = self._cleanup_pending_dir()
        marker_dir.mkdir(parents=True, exist_ok=True)
        self._assert_under_base(staged.pending_marker)
        payload = {
            "scope": staged.scope,
            "object_id": staged.object_id,
            "tombstone": staged.tombstone_dir.resolve()
            .relative_to(self.base_dir.resolve())
            .as_posix(),
            "reason": reason,
        }
        temporary = staged.pending_marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(staged.pending_marker)

    def retry_pending_cleanups(self) -> int:
        marker_dir = self._cleanup_pending_dir()
        if not marker_dir.exists():
            return 0
        cleaned = 0
        for marker in sorted(marker_dir.glob("*.json")):
            self._assert_under_base(marker)
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                tombstone = self.base_dir / str(payload["tombstone"])
                self._assert_under_base(tombstone)
                self._safe_rmtree(tombstone)
                marker.unlink(missing_ok=True)
                cleaned += 1
            except Exception:
                continue
        return cleaned

    def _materialize_asset(
        self,
        asset: ParsedAsset,
        source_path: Path,
        target_dir: Path,
        *,
        scope: str,
    ) -> ParsedAsset:
        actual = self._inspect_upload_image(source_path)
        if actual["mime_type"] != asset.mime_type:
            raise DocumentParseError("Image asset MIME does not match validated upload")
        if actual["sha256"] != asset.sha256:
            raise DocumentParseError("Image asset hash does not match validated upload")
        metadata = dict(asset.metadata)
        for key in ("width", "height", "pixel_count", "byte_size"):
            expected = metadata.get(key)
            if expected is not None and int(expected) != int(actual[key]):
                raise DocumentParseError("Image asset metadata does not match validated upload")
        suffix = MATERIALIZED_MIME_TYPES[asset.mime_type]
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{uuid4()}{suffix}"
        self._assert_under_base(target_path)
        shutil.copyfile(source_path, target_path)
        metadata["materialized"] = True
        metadata["storage_scope"] = scope
        return replace(
            asset,
            storage_ref=self._storage_ref(target_path),
            sha256=str(actual["sha256"]),
            metadata=metadata,
        )

    @staticmethod
    def _can_materialize_from_upload(asset: ParsedAsset) -> bool:
        metadata = dict(asset.metadata or {})
        return (
            metadata.get("source_kind") == TRUSTED_UPLOAD_SOURCE_KIND
            and metadata.get("materialized") is False
            and asset.mime_type in MATERIALIZED_MIME_TYPES
        )

    @staticmethod
    def _mark_not_materialized(asset: ParsedAsset) -> ParsedAsset:
        metadata = dict(asset.metadata or {})
        metadata["materialized"] = False
        metadata["materialization_status"] = "asset_not_materialized"
        return replace(asset, metadata=metadata)

    @staticmethod
    def _inspect_upload_image(path: Path) -> dict[str, object]:
        data = path.read_bytes()
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            expected_mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            expected_mime = "image/jpeg"
        else:
            raise DocumentParseError("Image asset source is not a validated PNG/JPEG upload")
        try:
            with Image.open(path) as image:
                mime_type = image.get_format_mimetype()
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise DocumentParseError("Image asset source structure is invalid") from exc
        if mime_type != expected_mime:
            raise DocumentParseError("Image asset source MIME is invalid")
        if width <= 0 or height <= 0:
            raise DocumentParseError("Image asset source dimensions are invalid")
        return {
            "mime_type": mime_type,
            "width": width,
            "height": height,
            "pixel_count": width * height,
            "byte_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def _submission_dir(self, submission_id: str) -> Path:
        return self.base_dir / "submissions" / self._safe_id(submission_id)

    def _document_dir(self, document_id: str) -> Path:
        return self.base_dir / "documents" / self._safe_id(document_id)

    def _stage_assets_for_delete(
        self,
        scope: str,
        object_id: str,
        original_dir: Path,
    ) -> StagedAssetDeletion:
        self._assert_under_base(original_dir)
        safe_id = self._safe_id(object_id)
        tombstone_dir = self._trash_dir(scope) / f".{safe_id}.{uuid4().hex}.deleting"
        pending_marker = self._cleanup_pending_dir() / f"{scope}-{safe_id}-{uuid4().hex}.json"
        self._assert_under_base(tombstone_dir)
        self._assert_under_base(pending_marker)
        if not original_dir.exists():
            return StagedAssetDeletion(
                scope=scope,
                object_id=safe_id,
                original_dir=original_dir,
                tombstone_dir=tombstone_dir,
                pending_marker=pending_marker,
                moved=False,
            )
        tombstone_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            original_dir.replace(tombstone_dir)
        except OSError as exc:
            raise DocumentStoreError() from exc
        return StagedAssetDeletion(
            scope=scope,
            object_id=safe_id,
            original_dir=original_dir,
            tombstone_dir=tombstone_dir,
            pending_marker=pending_marker,
            moved=True,
        )

    def _trash_dir(self, scope: str) -> Path:
        return self.base_dir / ".trash" / f"{scope}s"

    def _cleanup_pending_dir(self) -> Path:
        return self.base_dir / ".cleanup_pending"

    @staticmethod
    def _safe_id(value: str) -> str:
        cleaned = value.strip()
        if value != cleaned or cleaned in {".", ".."} or SAFE_ID_PATTERN.fullmatch(cleaned) is None:
            raise DocumentStoreError()
        return cleaned

    def _safe_rmtree(self, path: Path) -> None:
        self._assert_under_base(path)
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError as exc:
                raise DocumentStoreError() from exc

    def _assert_under_base(self, path: Path) -> None:
        base = self.base_dir.resolve()
        resolved = path.resolve()
        if base == resolved:
            raise DocumentStoreError()
        if base not in resolved.parents:
            raise DocumentStoreError()

    def _storage_ref(self, path: Path) -> str:
        self._assert_under_base(path)
        relative = path.resolve().relative_to(self.base_dir.resolve()).as_posix()
        return f"document-asset://{relative}"
