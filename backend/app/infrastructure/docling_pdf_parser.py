"""Optional Docling PDF adapter.

Docling objects are normalized here and never leave the infrastructure boundary.
The dependency is intentionally lazy and optional; production keeps it disabled
until a fixed offline gate proves the candidate can replace the PyPDF baseline.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import queue
from html import escape
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.ingestion import (
    ParseQuality,
    ParseRequest,
    ParsedAsset,
    ParsedDocument,
    ParsedElement,
)


class DoclingPdfStructuredParser:
    name = "docling_pdf_candidate"

    def __init__(
        self,
        converter_factory: Callable[[], Any] | None = None,
        *,
        timeout_seconds: float = 20.0,
        worker_target: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.converter_factory = converter_factory
        self.timeout_seconds = timeout_seconds
        self.worker_target = worker_target or run_docling_worker

    @property
    def available(self) -> bool:
        return self.converter_factory is not None or find_spec("docling") is not None

    def parse(self, request: ParseRequest) -> ParsedDocument:
        if request.normalized_suffix != ".pdf":
            raise DocumentParseError("Docling candidate only supports PDF")
        if self.converter_factory is not None:
            document_data = self._parse_with_test_converter(request.path)
        else:
            document_data = self._parse_in_subprocess(request.path)
        parsed = self._normalize_document(document_data, request)
        if not parsed.elements or not parsed.text.strip():
            raise DocumentParseError("Docling candidate produced empty text")
        return parsed

    def _parse_with_test_converter(self, path: Path) -> dict[str, Any]:
        converter = self.converter_factory()
        try:
            result = converter.convert(path)
        except Exception as exc:
            raise DocumentParseError("Docling candidate parse failed") from exc
        return export_docling_document_data(result)

    def _parse_in_subprocess(self, path: Path) -> dict[str, Any]:
        if find_spec("docling") is None:
            raise DocumentParseError("Docling is not installed")
        context = multiprocessing.get_context("spawn")
        output_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=self.worker_target,
            args=(str(path), output_queue),
            name="docling-pdf-candidate",
        )
        process.start()
        process.join(self.timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
            self._close_worker_resources(output_queue, process)
            raise DocumentParseError("Docling candidate worker timed out")
        try:
            message = output_queue.get(timeout=0.1)
        except queue.Empty as exc:
            self._close_worker_resources(output_queue, process)
            raise DocumentParseError("Docling candidate worker returned no output") from exc
        self._close_worker_resources(output_queue, process)
        if not isinstance(message, dict) or message.get("ok") is not True:
            code = "worker_error"
            if isinstance(message, dict):
                code = str(message.get("error_code") or code)
            raise DocumentParseError(f"Docling candidate worker failed: {code}")
        document = message.get("document")
        if not isinstance(document, dict):
            raise DocumentParseError("Docling candidate worker returned invalid output")
        return document

    @staticmethod
    def _close_worker_resources(output_queue: Any, process: Any) -> None:
        output_queue.close()
        output_queue.join_thread()
        close = getattr(process, "close", None)
        if callable(close):
            close()

    def _normalize_document(
        self, data: dict[str, Any], request: ParseRequest
    ) -> ParsedDocument:
        elements: list[ParsedElement] = []
        assets: list[ParsedAsset] = []
        page_count = _as_int(data.get("page_count")) or _page_count_from_pages(data.get("pages"))
        raw_elements = self._iter_raw_elements(data)
        order = 0
        for raw in raw_elements:
            kind = normalize_kind(str(raw.get("kind") or raw.get("label") or "paragraph"))
            text = str(raw.get("text") or raw.get("content") or "").strip()
            table_html = None
            if kind == "table":
                text, table_html = normalize_table(raw)
            if not text and kind != "image":
                continue
            order += 1
            if kind == "image":
                assets.append(build_asset(raw, order))
                continue
            elements.append(
                ParsedElement(
                    element_id=f"docling-{order}",
                    kind=kind,
                    text=text,
                    page_no=_as_int(raw.get("page_no") or raw.get("page")),
                    order=order,
                    bbox=normalize_bbox(raw.get("bbox") or raw.get("prov")),
                    table_html=table_html,
                    metadata={"parser": self.name},
                )
            )
        if not page_count:
            page_count = max((element.page_no or 0 for element in elements), default=1)
        warnings = (
            "Docling candidate output has not been promoted to the production baseline",
        )
        counts = {
            kind: sum(element.kind == kind for element in elements)
            for kind in ("title", "paragraph", "list", "table")
        }
        counts["asset"] = len(assets)
        return ParsedDocument(
            document_metadata={
                "file_name": request.file_name or request.path.name,
                "suffix": ".pdf",
                "page_count": page_count,
                "parser": self.name,
            },
            elements=tuple(elements),
            assets=tuple(assets),
            warnings=warnings,
            quality=ParseQuality(
                status="warning",
                counts=counts,
                page_results=tuple(
                    {"page": index, "kind": "docling_candidate"}
                    for index in range(1, page_count + 1)
                ),
                warnings=warnings,
                parser_name=self.name,
            ),
        )

    @staticmethod
    def _iter_raw_elements(data: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(data.get("elements"), list):
            return [item for item in data["elements"] if isinstance(item, dict)]
        items: list[dict[str, Any]] = []
        for key, kind in (
            ("texts", "paragraph"),
            ("headings", "title"),
            ("tables", "table"),
            ("pictures", "image"),
            ("images", "image"),
        ):
            for item in data.get(key) or ():
                if isinstance(item, dict):
                    normalized = dict(item)
                    normalized.setdefault("kind", kind)
                    items.append(normalized)
        return items


def run_docling_worker(path_text: str, output_queue: Any) -> None:
    configure_docling_offline_environment()
    try:
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(Path(path_text))
        output_queue.put({"ok": True, "document": export_docling_document_data(result)})
    except Exception:
        output_queue.put({"ok": False, "error_code": "docling_parse_failed"})


def configure_docling_offline_environment() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")


def export_docling_document_data(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    document = getattr(result, "document", result)
    if hasattr(document, "export_to_dict"):
        exported = document.export_to_dict()
        if isinstance(exported, dict):
            return exported
    if hasattr(document, "model_dump"):
        exported = document.model_dump(mode="json")
        if isinstance(exported, dict):
            return exported
    if hasattr(document, "export_to_markdown"):
        text = document.export_to_markdown().strip()
        return {
            "page_count": len(getattr(document, "pages", {}) or {1: None}),
            "elements": [{"kind": "paragraph", "text": text, "page_no": 1}],
        }
    raise DocumentParseError("Docling candidate output format is unsupported")


def normalize_kind(value: str) -> str:
    cleaned = value.lower()
    if cleaned in {"title", "heading", "section_header", "document_title"}:
        return "title"
    if cleaned in {"list", "list_item"}:
        return "list"
    if cleaned in {"table", "table_item"}:
        return "table"
    if cleaned in {"picture", "image", "embedded_image"}:
        return "image"
    return "paragraph"


def normalize_table(raw: dict[str, Any]) -> tuple[str, str]:
    rows = raw.get("rows")
    if isinstance(rows, list):
        normalized_rows = [
            [str(cell).strip() for cell in row]
            for row in rows
            if isinstance(row, list) and any(str(cell).strip() for cell in row)
        ]
        text = "\n".join(" | ".join(cell for cell in row) for row in normalized_rows)
        html = "<table>" + "".join(
            "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
            for row in normalized_rows
        ) + "</table>"
        return text, html
    text = str(raw.get("text") or raw.get("content") or "").strip()
    table_html = sanitize_table_html(str(raw.get("table_html") or raw.get("html") or ""))
    return text, table_html


def sanitize_table_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    table = soup.find("table")
    if table is None:
        return ""
    for tag in table.find_all(True):
        tag.attrs = {}
    return str(table)


def normalize_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, dict):
        for key in ("bbox", "bounding_box"):
            if key in value:
                return normalize_bbox(value[key])
        values = [value.get(key) for key in ("x0", "y0", "x1", "y1")]
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        values = list(value)
    else:
        return None
    try:
        floats = tuple(float(item) for item in values)
    except (TypeError, ValueError):
        return None
    if any(item < 0 or item > 1 for item in floats):
        return None
    x0, y0, x1, y1 = floats
    if x1 < x0 or y1 < y0:
        return None
    return floats


def build_asset(raw: dict[str, Any], order: int) -> ParsedAsset:
    storage_ref = str(raw.get("storage_ref") or f"docling://asset/{order}")
    digest_source = f"{storage_ref}:{raw.get('page_no') or raw.get('page') or ''}"
    return ParsedAsset(
        asset_id=f"docling-asset-{order}",
        kind="embedded_image",
        page_no=_as_int(raw.get("page_no") or raw.get("page")),
        mime_type=str(raw.get("mime_type") or "image/png"),
        storage_ref=storage_ref,
        sha256=str(raw.get("sha256") or hashlib.sha256(digest_source.encode()).hexdigest()),
        metadata={"parser": DoclingPdfStructuredParser.name},
    )


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _page_count_from_pages(value: Any) -> int | None:
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, list):
        return len(value)
    return None
