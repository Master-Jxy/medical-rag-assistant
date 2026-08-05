"""Shared file type policy for knowledge uploads and parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile, is_zipfile

from app.core.exceptions import DocumentParseError, UnsupportedFileTypeError


TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm"}


@dataclass(frozen=True, slots=True)
class FileTypeInfo:
    suffix: str
    mime_type: str
    label: str
    text_based: bool = False


class FileTypePolicy:
    _types = {
        ".pdf": FileTypeInfo(".pdf", "application/pdf", "PDF"),
        ".txt": FileTypeInfo(".txt", "text/plain", "TXT", text_based=True),
        ".md": FileTypeInfo(".md", "text/markdown", "Markdown", text_based=True),
        ".markdown": FileTypeInfo(
            ".markdown", "text/markdown", "Markdown", text_based=True
        ),
        ".html": FileTypeInfo(".html", "text/html", "HTML", text_based=True),
        ".htm": FileTypeInfo(".htm", "text/html", "HTML", text_based=True),
        ".docx": FileTypeInfo(
            ".docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "DOCX",
        ),
    }

    @classmethod
    def supported_suffixes(cls) -> tuple[str, ...]:
        return tuple(cls._types)

    @classmethod
    def accept_attribute(cls) -> str:
        return ",".join(cls.supported_suffixes())

    @classmethod
    def get(cls, suffix: str) -> FileTypeInfo:
        normalized = suffix.lower()
        info = cls._types.get(normalized)
        if info is None:
            raise UnsupportedFileTypeError()
        return info

    @classmethod
    def validate_path(cls, path: Path, suffix: str) -> FileTypeInfo:
        info = cls.get(suffix)
        if info.suffix == ".pdf":
            cls._validate_pdf(path)
        elif info.suffix == ".docx":
            cls._validate_docx(path)
        elif info.suffix in TEXT_SUFFIXES:
            cls._validate_utf8_text(path)
        else:
            raise UnsupportedFileTypeError()
        return info

    @staticmethod
    def mime_type_for_suffix(suffix: str) -> str:
        return FileTypePolicy.get(suffix).mime_type

    @staticmethod
    def _validate_pdf(path: Path) -> None:
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise DocumentParseError("文件内容与PDF格式不匹配")

    @staticmethod
    def _validate_utf8_text(path: Path) -> None:
        data = path.read_bytes()
        if b"\x00" in data:
            raise DocumentParseError("文本文件包含非法空字节")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("文本文件必须使用UTF-8编码") from exc

    @staticmethod
    def _validate_docx(path: Path) -> None:
        if not is_zipfile(path):
            raise DocumentParseError("DOCX文件结构无效")
        try:
            with ZipFile(path) as package:
                names = set(package.namelist())
                required = {"[Content_Types].xml", "word/document.xml"}
                if not required.issubset(names):
                    raise DocumentParseError("DOCX缺少必要OOXML文档结构")
                if "word/vbaProject.bin" in names:
                    raise DocumentParseError("DOCX不能包含宏")
                for name in names:
                    if not name.endswith(".rels"):
                        continue
                    content = package.read(name).decode("utf-8", errors="ignore")
                    if 'TargetMode="External"' in content:
                        raise DocumentParseError("DOCX不能包含外部关系")
        except BadZipFile as exc:
            raise DocumentParseError("DOCX文件结构无效") from exc
