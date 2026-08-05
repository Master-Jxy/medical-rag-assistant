"""Factory for wiring optional infrastructure parsers into knowledge ingestion."""

from app.core.config import Settings
from app.infrastructure.docling_pdf_parser import DoclingPdfStructuredParser
from app.modules.knowledge.parser import LocalDocumentParser


def create_knowledge_document_parser(settings: Settings) -> LocalDocumentParser:
    candidate = (
        DoclingPdfStructuredParser()
        if settings.docling_pdf_candidate_enabled
        else None
    )
    return LocalDocumentParser(
        pdf_candidate=candidate,
        pdf_candidate_enabled=settings.docling_pdf_candidate_enabled,
        pdf_candidate_max_pages=settings.docling_pdf_max_pages,
        pdf_candidate_max_file_size_bytes=settings.docling_pdf_max_file_size_bytes,
        pdf_candidate_timeout_seconds=settings.docling_pdf_timeout_seconds,
    )
