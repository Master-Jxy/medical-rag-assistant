"""Structured document parsing contracts for knowledge ingestion."""

from app.modules.knowledge.ingestion.contracts import (
    DocumentParserPort,
    ParseQuality,
    ParseRequest,
    ParsedAsset,
    ParsedDocument,
    ParsedElement,
)
from app.modules.knowledge.ingestion.registry import ParserRegistration, ParserRegistry

__all__ = [
    "DocumentParserPort",
    "ParseQuality",
    "ParseRequest",
    "ParsedAsset",
    "ParsedDocument",
    "ParsedElement",
    "ParserRegistration",
    "ParserRegistry",
]
