"""Shared file type policy for knowledge uploads and parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, is_zipfile

from app.core.exceptions import DocumentParseError, UnsupportedFileTypeError


TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm"}
DOCX_MAX_ENTRIES = 256
DOCX_MAX_ENTRY_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
DOCX_MAX_COMPRESSION_RATIO = 100
DOCX_MAX_RELS_UNCOMPRESSED_BYTES = 256 * 1024


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
    def preview_mime_type_for_suffix(suffix: str) -> str:
        info = FileTypePolicy.get(suffix)
        if info.suffix in {".html", ".htm"}:
            return "text/plain; charset=utf-8"
        return info.mime_type

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
                infos = package.infolist()
                FileTypePolicy._validate_docx_zip_metadata(infos)
                names = {info.filename for info in infos}
                required = {"[Content_Types].xml", "word/document.xml"}
                if not required.issubset(names):
                    raise DocumentParseError("DOCX缺少必要OOXML文档结构")
                if any(name.lower() == "word/vbaproject.bin" for name in names):
                    raise DocumentParseError("DOCX不能包含宏")
                for info in infos:
                    if not info.filename.lower().endswith(".rels"):
                        continue
                    if info.file_size > DOCX_MAX_RELS_UNCOMPRESSED_BYTES:
                        raise DocumentParseError("DOCX关系文件过大")
                    FileTypePolicy._validate_docx_relationships(package.read(info))
        except BadZipFile as exc:
            raise DocumentParseError("DOCX文件结构无效") from exc

    @staticmethod
    def _validate_docx_zip_metadata(infos) -> None:
        if len(infos) > DOCX_MAX_ENTRIES:
            raise DocumentParseError("DOCX包含过多文件条目")
        total_uncompressed = 0
        seen_names: set[str] = set()
        for info in infos:
            FileTypePolicy._validate_zip_entry_path(info.filename)
            if info.filename in seen_names:
                raise DocumentParseError("DOCX包含重复文件条目")
            seen_names.add(info.filename)
            if info.flag_bits & 0x1:
                raise DocumentParseError("DOCX不能包含加密条目")
            if info.file_size > DOCX_MAX_ENTRY_UNCOMPRESSED_BYTES:
                raise DocumentParseError("DOCX单个文件条目过大")
            total_uncompressed += info.file_size
            if total_uncompressed > DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise DocumentParseError("DOCX展开后总体积过大")
            if info.file_size > 0 and info.compress_size <= 0:
                raise DocumentParseError("DOCX压缩元数据异常")
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > DOCX_MAX_COMPRESSION_RATIO:
                    raise DocumentParseError("DOCX压缩比异常")

    @staticmethod
    def _validate_zip_entry_path(name: str) -> None:
        if not name or "\x00" in name or "\\" in name or ":" in name:
            raise DocumentParseError("DOCX文件条目路径异常")
        normalized = name.rstrip("/")
        if not normalized:
            raise DocumentParseError("DOCX文件条目路径异常")
        path = PurePosixPath(normalized)
        if path.is_absolute():
            raise DocumentParseError("DOCX文件条目路径异常")
        parts = normalized.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise DocumentParseError("DOCX文件条目路径异常")

    @staticmethod
    def _validate_docx_relationships(content: bytes) -> None:
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise DocumentParseError("DOCX关系XML无效") from exc
        for node in root.iter():
            if FileTypePolicy._local_xml_name(node.tag) != "Relationship":
                continue
            for key, value in node.attrib.items():
                if (
                    FileTypePolicy._local_xml_name(key) == "TargetMode"
                    and value.lower() == "external"
                ):
                    raise DocumentParseError("DOCX不能包含外部关系")

    @staticmethod
    def _local_xml_name(name: str) -> str:
        return name.rsplit("}", 1)[-1]
