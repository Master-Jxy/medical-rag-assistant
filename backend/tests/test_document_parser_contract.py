"""Stage 24.1: normalized document parser contract and compatibility."""

from pathlib import Path

import pytest

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.ingestion import (
    ParseQuality,
    ParseRequest,
    ParsedDocument,
    ParsedElement,
    ParserRegistration,
    ParserRegistry,
)
from app.modules.knowledge.parser import LocalDocumentParser, ParsedPreview


class DummyParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.called = False

    def parse(self, request: ParseRequest) -> ParsedDocument:
        self.called = True
        return ParsedDocument(
            document_metadata={
                "file_name": request.file_name or request.path.name,
                "page_count": 1,
            },
            elements=(
                ParsedElement(
                    element_id="dummy-1",
                    kind="paragraph",
                    text=self.text,
                    page_no=1,
                    order=1,
                ),
            ),
            quality=ParseQuality(status="pass", counts={"text": 1}),
        )


def test_registry_selects_by_explicit_suffix_and_rejects_unknown(tmp_path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("医学资料", encoding="utf-8")
    txt_parser = DummyParser("TXT")
    pdf_parser = DummyParser("PDF")
    registry = ParserRegistry(
        [
            ParserRegistration("pdf", pdf_parser, suffixes=(".pdf",)),
            ParserRegistration("txt", txt_parser, suffixes=(".txt",)),
        ]
    )

    parsed = registry.parse(ParseRequest(path=path, suffix=".TXT"))

    assert parsed.text == "TXT"
    assert txt_parser.called is True
    assert pdf_parser.called is False
    with pytest.raises(DocumentParseError) as exc_info:
        registry.parse(ParseRequest(path=Path("missing.docx"), suffix=".docx"))
    assert exc_info.value.code == "DOCUMENT_PARSE_ERROR"


def test_local_parser_returns_normalized_document_and_legacy_preview(tmp_path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("第一段\n\n第二段", encoding="utf-8")
    parser = LocalDocumentParser()

    document = parser.parse_document(ParseRequest(path=path, suffix=".txt"))
    preview = parser.parse(path, ".txt")

    assert document.document_metadata["parser"] == "local_pdf_txt"
    assert [element.text for element in document.elements] == ["第一段\n\n第二段"]
    assert document.assets == ()
    assert document.quality.status == "pass"
    assert document.quality.counts == {
        "text": 1,
        "table_like": 0,
        "scanned_or_image": 0,
    }
    assert preview == ParsedPreview(
        "第一段\n\n第二段",
        1,
        (),
        {
            "status": "pass",
            "counts": {
                "text": 1,
                "table_like": 0,
                "scanned_or_image": 0,
            },
            "page_results": [
                {"page": 1, "kind": "text", "text_chars": 8, "image_count": 0}
            ],
        },
    )


def test_legacy_preview_is_projected_from_structured_document() -> None:
    document = ParsedDocument(
        document_metadata={"page_count": 1},
        elements=(
            ParsedElement(
                element_id="e1",
                kind="paragraph",
                text="x" * 8001,
                page_no=1,
                order=1,
            ),
        ),
        warnings=("source warning",),
        quality=ParseQuality(status="warning", counts={"text": 1}),
    )

    preview = ParsedPreview.from_document(document)

    assert len(preview.text) == 8000
    assert preview.warnings == ("source warning", "预览已截断")
    assert preview.quality == {
        "status": "warning",
        "counts": {"text": 1},
        "page_results": [],
    }
