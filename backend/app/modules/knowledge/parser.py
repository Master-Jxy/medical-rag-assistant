"""无模型文档预解析Port与本地适配器。"""

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Protocol

from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from langchain_community.document_loaders import PyPDFLoader
from markdown_it import MarkdownIt
from pypdf import PdfReader

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.ingestion import (
    DocumentParserPort,
    FileTypePolicy,
    ParseQuality,
    ParseRequest,
    ParsedDocument,
    ParsedElement,
    ParserRegistration,
    ParserRegistry,
)


@dataclass(frozen=True, slots=True)
class ParsedPreview:
    text: str
    page_count: int
    warnings: tuple[str, ...] = ()
    quality: dict[str, object] | None = None

    @classmethod
    def from_document(cls, document: ParsedDocument) -> "ParsedPreview":
        text = document.text
        warnings = list(document.warnings)
        if len(text) > 8000:
            warnings.append("预览已截断")
        return cls(
            text=text[:8000],
            page_count=document.page_count,
            warnings=tuple(dict.fromkeys(warnings)),
            quality=document.quality.to_legacy_dict(),
        )


class ParserPort(Protocol):
    def parse(self, path: Path, suffix: str) -> ParsedPreview: ...


class LocalStructuredDocumentParser:
    name = "local_pdf_txt"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        path = request.path
        suffix = request.normalized_suffix
        try:
            pages = (
                PyPDFLoader(str(path)).load()
                if suffix == ".pdf"
                else [path.read_text(encoding="utf-8")]
            )
            texts = [
                item.page_content if hasattr(item, "page_content") else item
                for item in pages
            ]
        except Exception as exc:
            raise DocumentParseError("无法解析文档，请确认文件内容和编码正确") from exc
        cleaned = [text.strip() for text in texts if text.strip()]
        if not cleaned:
            raise DocumentParseError()
        combined = "\n\n".join(cleaned)
        warnings = list(("预览已截断",) if len(combined) > 8000 else ())
        page_results: list[dict[str, object]] = []
        if suffix == ".pdf":
            pdf_results, pdf_warnings = self._inspect_pdf_pages(path)
            page_results.extend(pdf_results)
            warnings.extend(pdf_warnings)
        else:
            page_results.append({"page": 1, "kind": "text", "text_chars": len(combined), "image_count": 0})
        counts = {
            kind: sum(item["kind"] == kind for item in page_results)
            for kind in ("text", "table_like", "scanned_or_image")
        }
        deduped_warnings = tuple(dict.fromkeys(warnings))
        elements = tuple(
            ParsedElement(
                element_id=f"element-{index}",
                kind="paragraph",
                text=text,
                page_no=index,
                order=index,
                metadata={"source": "local", "suffix": suffix},
            )
            for index, text in enumerate(cleaned, start=1)
        )
        return ParsedDocument(
            document_metadata={
                "file_name": request.file_name or path.name,
                "suffix": suffix,
                "page_count": len(pages),
                "parser": self.name,
            },
            elements=elements,
            assets=(),
            warnings=deduped_warnings,
            quality=ParseQuality(
                status="warning" if deduped_warnings else "pass",
                counts=counts,
                page_results=tuple(page_results),
                warnings=deduped_warnings,
                parser_name=self.name,
            ),
        )

    @staticmethod
    def _inspect_pdf_pages(
        path: Path,
    ) -> tuple[list[dict[str, object]], list[str]]:
        results: list[dict[str, object]] = []
        warnings: list[str] = []
        try:
            reader = PdfReader(str(path))
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                resources = page.get("/Resources") or {}
                xobjects = (
                    resources.get("/XObject")
                    if hasattr(resources, "get")
                    else None
                )
                image_count = len(xobjects.get_object()) if xobjects else 0
                table_like = "|" in text or any(
                    "  " in line for line in text.splitlines()
                )
                if len(text) < 30 and image_count:
                    kind = "scanned_or_image"
                    warnings.append(
                        f"第{index}页疑似扫描页或图片，文本可能缺失"
                    )
                elif table_like:
                    kind = "table_like"
                    warnings.append(
                        f"第{index}页包含疑似表格，需人工核对结构"
                    )
                else:
                    kind = "text"
                results.append(
                    {
                        "page": index,
                        "kind": kind,
                        "text_chars": len(text),
                        "image_count": image_count,
                    }
                )
        except Exception as exc:
            raise DocumentParseError(
                "PDF逐页质量检查失败，不能安全进入审核"
            ) from exc
        return results, warnings


class DocxStructuredDocumentParser:
    name = "local_docx"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        try:
            document = DocxDocument(str(request.path))
        except Exception as exc:
            raise DocumentParseError("无法解析DOCX文档") from exc
        elements: list[ParsedElement] = []
        order = 0
        for child in document.element.body:
            if child.tag.endswith("}p"):
                paragraph = next(
                    item for item in document.paragraphs if item._p is child
                )
                text = paragraph.text.strip()
                if not text:
                    continue
                order += 1
                style_name = (paragraph.style.name or "").lower()
                is_list = paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None
                kind = (
                    "title"
                    if style_name.startswith("heading") or style_name.startswith("标题")
                    else "list"
                    if is_list or "list" in style_name
                    else "paragraph"
                )
                elements.append(
                    ParsedElement(
                        element_id=f"docx-{order}",
                        kind=kind,
                        text=text,
                        page_no=None,
                        order=order,
                        metadata={"style": paragraph.style.name or ""},
                    )
                )
            elif child.tag.endswith("}tbl"):
                table = next(item for item in document.tables if item._tbl is child)
                rows = [
                    [cell.text.strip() for cell in row.cells]
                    for row in table.rows
                    if any(cell.text.strip() for cell in row.cells)
                ]
                if not rows:
                    continue
                order += 1
                text = "\n".join(" | ".join(cell for cell in row) for row in rows)
                html_rows = "".join(
                    "<tr>"
                    + "".join(f"<td>{escape(cell)}</td>" for cell in row)
                    + "</tr>"
                    for row in rows
                )
                elements.append(
                    ParsedElement(
                        element_id=f"docx-{order}",
                        kind="table",
                        text=text,
                        page_no=None,
                        order=order,
                        table_html=f"<table>{html_rows}</table>",
                    )
                )
        if not elements:
            raise DocumentParseError()
        return _build_document(request, self.name, tuple(elements))


class MarkdownStructuredDocumentParser:
    name = "local_markdown"

    def __init__(self) -> None:
        self.markdown = MarkdownIt("commonmark").enable("table")

    def parse(self, request: ParseRequest) -> ParsedDocument:
        text = _read_utf8(request.path)
        tokens = self.markdown.parse(text)
        elements: list[ParsedElement] = []
        order = 0
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type in {"heading_open", "paragraph_open"}:
                inline = tokens[index + 1] if index + 1 < len(tokens) else None
                content = (inline.content if inline and inline.type == "inline" else "").strip()
                if content:
                    order += 1
                    kind = "title" if token.type == "heading_open" else "paragraph"
                    elements.append(
                        ParsedElement(
                            element_id=f"markdown-{order}",
                            kind=kind,
                            text=content,
                            page_no=1,
                            order=order,
                            metadata={"markup": token.tag},
                        )
                    )
            elif token.type == "list_item_open":
                parts: list[str] = []
                depth = token.level
                index += 1
                while index < len(tokens) and not (
                    tokens[index].type == "list_item_close"
                    and tokens[index].level == depth
                ):
                    if tokens[index].type == "inline" and tokens[index].content.strip():
                        parts.append(tokens[index].content.strip())
                    index += 1
                content = " ".join(parts).strip()
                if content:
                    order += 1
                    elements.append(
                        ParsedElement(
                            element_id=f"markdown-{order}",
                            kind="list",
                            text=content,
                            page_no=1,
                            order=order,
                        )
                    )
            elif token.type == "table_open":
                table_text, table_html, index = _consume_markdown_table(tokens, index)
                if table_text:
                    order += 1
                    elements.append(
                        ParsedElement(
                            element_id=f"markdown-{order}",
                            kind="table",
                            text=table_text,
                            page_no=1,
                            order=order,
                            table_html=table_html,
                        )
                    )
            index += 1
        if not elements:
            raise DocumentParseError()
        return _build_document(request, self.name, tuple(elements), page_count=1)


class HtmlStructuredDocumentParser:
    name = "local_html"
    dangerous_tags = {"script", "style", "form", "iframe", "object", "embed", "noscript"}

    def parse(self, request: ParseRequest) -> ParsedDocument:
        soup = BeautifulSoup(_read_utf8(request.path), "html.parser")
        for tag in soup.find_all(self.dangerous_tags):
            tag.decompose()
        for tag in soup.find_all(True):
            tag.attrs = {}
        root = soup.body or soup
        elements: list[ParsedElement] = []
        order = 0
        for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
            if any(parent.name == "table" for parent in node.parents) and node.name != "table":
                continue
            text = node.get_text(" ", strip=True)
            if not text:
                continue
            order += 1
            kind = (
                "title"
                if node.name and node.name.startswith("h")
                else "list"
                if node.name == "li"
                else "table"
                if node.name == "table"
                else "paragraph"
            )
            elements.append(
                ParsedElement(
                    element_id=f"html-{order}",
                    kind=kind,
                    text=text,
                    page_no=1,
                    order=order,
                    table_html=str(node) if kind == "table" else None,
                    metadata={"tag": node.name or ""},
                )
            )
        if not elements:
            raise DocumentParseError()
        return _build_document(request, self.name, tuple(elements), page_count=1)


def _read_utf8(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("文本文件必须使用UTF-8编码") from exc
    if not text.strip():
        raise DocumentParseError()
    return text


def _build_document(
    request: ParseRequest,
    parser_name: str,
    elements: tuple[ParsedElement, ...],
    *,
    page_count: int | None = None,
    warnings: tuple[str, ...] = (),
) -> ParsedDocument:
    counts = {
        kind: sum(element.kind == kind for element in elements)
        for kind in ("title", "paragraph", "list", "table")
    }
    return ParsedDocument(
        document_metadata={
            "file_name": request.file_name or request.path.name,
            "suffix": request.normalized_suffix,
            "page_count": page_count or max(
                (element.page_no or 0 for element in elements), default=1
            ),
            "parser": parser_name,
        },
        elements=elements,
        assets=(),
        warnings=warnings,
        quality=ParseQuality(
            status="warning" if warnings else "pass",
            counts=counts,
            page_results=(),
            warnings=warnings,
            parser_name=parser_name,
        ),
    )


def _consume_markdown_table(tokens, start: int) -> tuple[str, str, int]:
    rows: list[list[str]] = []
    current_row: list[str] | None = None
    index = start + 1
    while index < len(tokens) and tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "tr_open":
            current_row = []
        elif token.type == "tr_close":
            if current_row and any(current_row):
                rows.append(current_row)
            current_row = None
        elif token.type == "inline" and current_row is not None:
            current_row.append(token.content.strip())
        index += 1
    text = "\n".join(" | ".join(cell for cell in row) for row in rows)
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return text, f"<table>{html_rows}</table>" if rows else "", index


def build_default_parser_registry() -> ParserRegistry:
    local_pdf_txt = LocalStructuredDocumentParser()
    markdown = MarkdownStructuredDocumentParser()
    return ParserRegistry(
        [
            ParserRegistration(
                name=LocalStructuredDocumentParser.name,
                parser=local_pdf_txt,
                suffixes=(".pdf", ".txt"),
                mime_types=("application/pdf", "text/plain"),
            ),
            ParserRegistration(
                name=DocxStructuredDocumentParser.name,
                parser=DocxStructuredDocumentParser(),
                suffixes=(".docx",),
                mime_types=(FileTypePolicy.mime_type_for_suffix(".docx"),),
            ),
            ParserRegistration(
                name=MarkdownStructuredDocumentParser.name,
                parser=markdown,
                suffixes=(".md", ".markdown"),
                mime_types=("text/markdown",),
            ),
            ParserRegistration(
                name=HtmlStructuredDocumentParser.name,
                parser=HtmlStructuredDocumentParser(),
                suffixes=(".html", ".htm"),
                mime_types=("text/html",),
            ),
        ]
    )


class LocalDocumentParser:
    def __init__(self, registry: ParserRegistry | None = None) -> None:
        self.registry = registry or build_default_parser_registry()

    def parse_document(self, request: ParseRequest) -> ParsedDocument:
        return self.registry.parse(request)

    def parse(self, path: Path, suffix: str) -> ParsedPreview:
        document = self.parse_document(
            ParseRequest(path=path, suffix=suffix, file_name=path.name)
        )
        return ParsedPreview.from_document(document)
