"""无模型文档预解析Port与本地适配器。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from langchain_community.document_loaders import PyPDFLoader

from app.core.exceptions import DocumentParseError


@dataclass(frozen=True, slots=True)
class ParsedPreview:
    text: str
    page_count: int
    warnings: tuple[str, ...] = ()


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
        warnings = ("预览已截断",) if len(combined) > 8000 else ()
        return ParsedPreview(combined[:8000], len(pages), warnings)
