"""无模型文档预解析Port与本地适配器。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from langchain_community.document_loaders import PyPDFLoader
from pypdf import PdfReader

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.ingestion import (
    DocumentParserPort,
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


def build_default_parser_registry() -> ParserRegistry:
    return ParserRegistry(
        [
            ParserRegistration(
                name=LocalStructuredDocumentParser.name,
                parser=LocalStructuredDocumentParser(),
                suffixes=(".pdf", ".txt"),
                mime_types=("application/pdf", "text/plain"),
            )
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
