"""Controlled storage for materialized document image assets."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.core.exceptions import DocumentStoreError
from app.modules.knowledge.ingestion import ParsedAsset, ParsedDocument


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
        materialized = tuple(
            self._materialize_asset(asset, source_path, target_dir, scope="submission")
            for asset in document.assets
        )
        return ParsedDocument(
            document_metadata=document.document_metadata,
            elements=document.elements,
            assets=materialized,
            warnings=document.warnings,
            quality=document.quality,
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

    def _materialize_asset(
        self,
        asset: ParsedAsset,
        source_path: Path,
        target_dir: Path,
        *,
        scope: str,
    ) -> ParsedAsset:
        if asset.mime_type not in {"image/png", "image/jpeg"}:
            raise DocumentStoreError()
        suffix = ".png" if asset.mime_type == "image/png" else ".jpg"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{uuid4()}{suffix}"
        self._assert_under_base(target_path)
        shutil.copyfile(source_path, target_path)
        digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
        metadata = dict(asset.metadata)
        metadata["materialized"] = True
        metadata["storage_scope"] = scope
        return replace(
            asset,
            storage_ref=self._storage_ref(target_path),
            sha256=digest,
            metadata=metadata,
        )

    def _submission_dir(self, submission_id: str) -> Path:
        return self.base_dir / "submissions" / self._safe_id(submission_id)

    def _document_dir(self, document_id: str) -> Path:
        return self.base_dir / "documents" / self._safe_id(document_id)

    @staticmethod
    def _safe_id(value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char in cleaned for char in {"/", "\\", ":", "\x00"}):
            raise DocumentStoreError()
        return cleaned

    def _safe_rmtree(self, path: Path) -> None:
        self._assert_under_base(path)
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError:
                pass

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
