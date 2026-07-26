"""无模型文档预解析Port与本地适配器。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from langchain_community.document_loaders import PyPDFLoader
from pypdf import PdfReader

from app.core.exceptions import DocumentParseError


@dataclass(frozen=True, slots=True)
class ParsedPreview:
    text: str
    page_count: int
    warnings: tuple[str, ...] = ()
    quality: dict[str, object] | None = None


class ParserPort(Protocol):
    def parse(self, path: Path, suffix: str) -> ParsedPreview: ...


class LocalDocumentParser:
    def parse(self, path: Path, suffix: str) -> ParsedPreview:
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
        quality = {"status": "warning" if warnings else "pass", "counts": counts, "page_results": page_results}
        return ParsedPreview(combined[:8000], len(pages), tuple(dict.fromkeys(warnings)), quality)

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
