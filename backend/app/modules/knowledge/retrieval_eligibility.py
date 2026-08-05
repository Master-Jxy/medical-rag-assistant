"""Published knowledge retrieval eligibility boundary."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.knowledge.deduplication import DuplicatePolicy
from app.modules.knowledge.models import DocumentVersion, KnowledgeDocument
from app.modules.rag.ports import (
    KnowledgeSearchOptions,
    KnowledgeSearchPort,
    RetrievedChunk,
)

RETRIEVAL_PUBLIC_STATUSES = ("published", "ready")
RETRIEVAL_OVERFETCH_FACTOR = 4
RETRIEVAL_OVERFETCH_EXTRA = 8
RETRIEVAL_OVERFETCH_MAX = 50


class DocumentRetrievalEligibilityPort(Protocol):
    """Batch-check whether documents are eligible to be returned by RAG/Agent."""

    def eligible_document_ids(self, document_ids: Iterable[str]) -> set[str]: ...


class SqlAlchemyDocumentRetrievalEligibility:
    """Evaluate retrieval eligibility from MySQL in one batch."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self.session = session
        self.now = now

    def eligible_document_ids(self, document_ids: Iterable[str]) -> set[str]:
        ids = sorted({item for item in document_ids if item})
        if not ids:
            return set()
        rows = self.session.execute(
            select(KnowledgeDocument, DocumentVersion)
            .outerjoin(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.id.in_(ids))
        ).all()
        now = self.now or datetime.now(timezone.utc)
        eligible: set[str] = set()
        for document, version in rows:
            if document.status not in RETRIEVAL_PUBLIC_STATUSES:
                continue
            if DuplicatePolicy.governance_status(version, now=now) == "expired":
                continue
            eligible.add(document.id)
        return eligible


class EligibilityFilteredKnowledgeSearch:
    """Decorate a SearchPort with DB-backed published/expiry filtering."""

    def __init__(
        self,
        inner: KnowledgeSearchPort,
        eligibility: DocumentRetrievalEligibilityPort,
        *,
        overfetch_factor: int = RETRIEVAL_OVERFETCH_FACTOR,
        overfetch_extra: int = RETRIEVAL_OVERFETCH_EXTRA,
        overfetch_max: int = RETRIEVAL_OVERFETCH_MAX,
    ) -> None:
        self.inner = inner
        self.eligibility = eligibility
        self.overfetch_factor = overfetch_factor
        self.overfetch_extra = overfetch_extra
        self.overfetch_max = overfetch_max

    def search(
        self,
        query: str,
        top_k: int,
        options: KnowledgeSearchOptions | None = None,
    ) -> list[RetrievedChunk]:
        requested = self._overfetch_limit(top_k)
        if options is None:
            chunks = self.inner.search(query, requested)
        else:
            chunks = self.inner.search(query, requested, options)
        eligible = self.eligibility.eligible_document_ids(
            chunk.document_id for chunk in chunks if chunk.document_id
        )
        return [
            chunk
            for chunk in chunks
            if chunk.document_id is not None and chunk.document_id in eligible
        ][:top_k]

    def _overfetch_limit(self, top_k: int) -> int:
        if top_k <= 0:
            return 0
        return min(
            max(top_k * self.overfetch_factor, top_k + self.overfetch_extra),
            self.overfetch_max,
        )
