"""Capability-based parser registry for knowledge ingestion."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import DocumentParseError
from app.modules.knowledge.ingestion.contracts import (
    DocumentParserPort,
    ParseRequest,
    ParsedDocument,
)


@dataclass(frozen=True, slots=True)
class ParserRegistration:
    name: str
    parser: DocumentParserPort
    suffixes: tuple[str, ...] = ()
    mime_types: tuple[str, ...] = ()

    def matches(self, request: ParseRequest) -> bool:
        suffixes = {item.lower() for item in self.suffixes}
        mime_types = {item.lower() for item in self.mime_types}
        return (
            bool(request.normalized_suffix and request.normalized_suffix in suffixes)
            or bool(request.mime_type and request.mime_type.lower() in mime_types)
        )


class ParserRegistry:
    def __init__(self, registrations: list[ParserRegistration] | None = None) -> None:
        self._registrations = tuple(registrations or ())

    @property
    def registrations(self) -> tuple[ParserRegistration, ...]:
        return self._registrations

    def select(self, request: ParseRequest) -> ParserRegistration:
        for registration in self._registrations:
            if registration.matches(request):
                return registration
        raise DocumentParseError("没有可用解析器支持该文件格式")

    def parse(self, request: ParseRequest) -> ParsedDocument:
        return self.select(request).parser.parse(request)
