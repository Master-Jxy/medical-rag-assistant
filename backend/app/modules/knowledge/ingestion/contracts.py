"""Stable normalized parsing objects used inside the knowledge module."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol


BBox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ParseRequest:
    path: Path
    suffix: str
    mime_type: str | None = None
    file_name: str | None = None
    options: Mapping[str, object] = field(default_factory=dict)

    @property
    def normalized_suffix(self) -> str:
        return self.suffix.lower()


@dataclass(frozen=True, slots=True)
class ParsedElement:
    element_id: str
    kind: str
    text: str
    page_no: int | None
    order: int
    bbox: BBox | None = None
    table_html: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedAsset:
    asset_id: str
    kind: str
    page_no: int | None
    mime_type: str
    storage_ref: str
    sha256: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParseQuality:
    status: str
    counts: Mapping[str, int] = field(default_factory=dict)
    page_results: tuple[Mapping[str, object], ...] = ()
    warnings: tuple[str, ...] = ()
    parser_name: str = "unknown"

    def to_legacy_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "counts": dict(self.counts),
            "page_results": [dict(item) for item in self.page_results],
        }


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    document_metadata: Mapping[str, object]
    elements: tuple[ParsedElement, ...]
    assets: tuple[ParsedAsset, ...] = ()
    warnings: tuple[str, ...] = ()
    quality: ParseQuality = field(default_factory=lambda: ParseQuality(status="pass"))

    @property
    def text(self) -> str:
        return "\n\n".join(
            element.text.strip() for element in self.elements if element.text.strip()
        )

    @property
    def page_count(self) -> int:
        value = self.document_metadata.get("page_count")
        if isinstance(value, int):
            return value
        pages = [element.page_no for element in self.elements if element.page_no]
        return max(pages, default=0)


class DocumentParserPort(Protocol):
    def parse(self, request: ParseRequest) -> ParsedDocument: ...
