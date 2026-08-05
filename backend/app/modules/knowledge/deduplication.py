"""Deterministic duplicate and version governance policy."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.knowledge.models import (
    DocumentVersion,
    KnowledgeDocument,
    KnowledgeSubmission,
)

NORMALIZED_TEXT_HASH_VERSION = "normalized_text_sha256_v1"
NEAR_DUPLICATE_FINGERPRINT_VERSION = "simhash64_v1"
NEAR_DUPLICATE_DISTANCE_THRESHOLD = 8
MAX_NORMALIZED_TEXT_CHARS = 250_000
TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)


@dataclass(frozen=True)
class TextFingerprint:
    normalized_text_hash: str | None
    normalized_text_hash_version: str | None
    near_duplicate_fingerprint: str | None
    near_duplicate_fingerprint_version: str | None


@dataclass(frozen=True)
class DuplicateCandidate:
    duplicate_type: str
    candidate_document_id: str
    candidate_file_name: str
    candidate_version: int
    score: float | None
    distance: int | None
    threshold: int | None
    reason: str


class DuplicatePolicy:
    @staticmethod
    def fingerprint_text(text: str | None) -> TextFingerprint:
        normalized = normalize_text(text or "")
        if not normalized:
            return TextFingerprint(None, None, None, None)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        simhash = simhash64(normalized)
        return TextFingerprint(
            normalized_text_hash=digest,
            normalized_text_hash_version=NORMALIZED_TEXT_HASH_VERSION,
            near_duplicate_fingerprint=f"{simhash:016x}",
            near_duplicate_fingerprint_version=NEAR_DUPLICATE_FINGERPRINT_VERSION,
        )

    @staticmethod
    def governance_status(
        version: DocumentVersion | None,
        *,
        now: datetime | None = None,
    ) -> str:
        if version is None:
            return "current"
        current_time = now or datetime.now(timezone.utc)
        if _is_at_or_before(version.expires_at, current_time):
            return "expired"
        if version.review_status == "expired":
            return "expired"
        if version.review_status == "in_review":
            return "in_review"
        if _is_at_or_before(version.review_due_at, current_time):
            return "due"
        if version.review_status == "due":
            return "due"
        return "current"

    @staticmethod
    def assign_to_submission(record: KnowledgeSubmission) -> None:
        fingerprint = DuplicatePolicy.fingerprint_text(record.preview_text)
        record.normalized_text_hash = fingerprint.normalized_text_hash
        record.normalized_text_hash_version = fingerprint.normalized_text_hash_version
        record.near_duplicate_fingerprint = fingerprint.near_duplicate_fingerprint
        record.near_duplicate_fingerprint_version = (
            fingerprint.near_duplicate_fingerprint_version
        )

    @staticmethod
    def apply_to_version_from_submission(
        submission: KnowledgeSubmission,
        version: DocumentVersion,
        *,
        parser_version: str,
        corpus_version: str,
        change_reason: str | None = None,
    ) -> None:
        version.normalized_text_hash = submission.normalized_text_hash
        version.normalized_text_hash_version = submission.normalized_text_hash_version
        version.near_duplicate_fingerprint = submission.near_duplicate_fingerprint
        version.near_duplicate_fingerprint_version = (
            submission.near_duplicate_fingerprint_version
        )
        version.parser_version = parser_version
        version.corpus_version = corpus_version
        if change_reason:
            version.change_reason = change_reason


class DuplicateCandidateService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_submission(
        self,
        submission: KnowledgeSubmission,
        *,
        limit: int = 5,
    ) -> list[DuplicateCandidate]:
        return self._find_candidates(
            content_hash=submission.content_hash,
            normalized_text_hash=submission.normalized_text_hash,
            normalized_text_hash_version=submission.normalized_text_hash_version,
            near_duplicate_fingerprint=submission.near_duplicate_fingerprint,
            near_duplicate_fingerprint_version=submission.near_duplicate_fingerprint_version,
            exclude_document_id=submission.document_id,
            limit=limit,
        )

    def for_document(
        self,
        document: KnowledgeDocument,
        version: DocumentVersion | None,
        *,
        limit: int = 5,
    ) -> list[DuplicateCandidate]:
        return self._find_candidates(
            content_hash=document.content_hash,
            normalized_text_hash=version.normalized_text_hash if version else None,
            normalized_text_hash_version=(
                version.normalized_text_hash_version if version else None
            ),
            near_duplicate_fingerprint=(
                version.near_duplicate_fingerprint if version else None
            ),
            near_duplicate_fingerprint_version=(
                version.near_duplicate_fingerprint_version if version else None
            ),
            exclude_document_id=document.id,
            limit=limit,
        )

    def _find_candidates(
        self,
        *,
        content_hash: str | None,
        normalized_text_hash: str | None,
        normalized_text_hash_version: str | None,
        near_duplicate_fingerprint: str | None,
        near_duplicate_fingerprint_version: str | None,
        exclude_document_id: str | None,
        limit: int,
    ) -> list[DuplicateCandidate]:
        candidates: list[DuplicateCandidate] = []
        if content_hash:
            rows = self.session.execute(
                select(KnowledgeDocument, DocumentVersion)
                .outerjoin(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
                .where(
                    KnowledgeDocument.content_hash == content_hash,
                    KnowledgeDocument.id != exclude_document_id,
                )
                .limit(limit)
            ).all()
            candidates.extend(
                _candidate(
                    "exact",
                    document,
                    version,
                    score=1.0,
                    distance=0,
                    threshold=0,
                    reason="原始文件 SHA-256 完全相同",
                )
                for document, version in rows
            )
        if normalized_text_hash and normalized_text_hash_version:
            rows = self.session.execute(
                select(KnowledgeDocument, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
                .where(
                    DocumentVersion.normalized_text_hash == normalized_text_hash,
                    DocumentVersion.normalized_text_hash_version
                    == normalized_text_hash_version,
                    KnowledgeDocument.id != exclude_document_id,
                )
                .limit(limit)
            ).all()
            candidates.extend(
                _candidate(
                    "normalized",
                    document,
                    version,
                    score=1.0,
                    distance=0,
                    threshold=0,
                    reason="规范化正文 SHA-256 完全相同",
                )
                for document, version in rows
            )
        if near_duplicate_fingerprint and near_duplicate_fingerprint_version:
            target = int(near_duplicate_fingerprint, 16)
            rows = self.session.execute(
                select(KnowledgeDocument, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.document_id == KnowledgeDocument.id)
                .where(
                    DocumentVersion.near_duplicate_fingerprint.is_not(None),
                    DocumentVersion.near_duplicate_fingerprint_version
                    == near_duplicate_fingerprint_version,
                    KnowledgeDocument.id != exclude_document_id,
                )
            ).all()
            near: list[DuplicateCandidate] = []
            for document, version in rows:
                if version.normalized_text_hash == normalized_text_hash:
                    continue
                distance = hamming_distance(
                    target, int(version.near_duplicate_fingerprint, 16)
                )
                if distance <= NEAR_DUPLICATE_DISTANCE_THRESHOLD:
                    near.append(
                        _candidate(
                            "near",
                            document,
                            version,
                            score=round(1 - distance / 64, 4),
                            distance=distance,
                            threshold=NEAR_DUPLICATE_DISTANCE_THRESHOLD,
                            reason="近重复 SimHash 距离低于阈值",
                        )
                    )
            near.sort(key=lambda item: (item.distance or 0, item.candidate_document_id))
            candidates.extend(near[:limit])
        return _dedupe_candidates(candidates)[:limit]


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text[:MAX_NORMALIZED_TEXT_CHARS])
    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def simhash64(text: str) -> int:
    tokens = _tokens(text)
    if not tokens:
        return 0
    weights = [0] * 64
    for token in tokens:
        digest = int.from_bytes(
            hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(),
            "big",
        )
        for bit in range(64):
            weights[bit] += 1 if digest & (1 << bit) else -1
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _tokens(text: str) -> list[str]:
    base = TOKEN_PATTERN.findall(text)
    cjk = [token for token in base if len(token) == 1 and "\u4e00" <= token <= "\u9fff"]
    cjk_bigrams = [f"{left}{right}" for left, right in zip(cjk, cjk[1:])]
    return [*base, *cjk_bigrams]


def _candidate(
    duplicate_type: str,
    document: KnowledgeDocument,
    version: DocumentVersion | None,
    *,
    score: float | None,
    distance: int | None,
    threshold: int | None,
    reason: str,
) -> DuplicateCandidate:
    return DuplicateCandidate(
        duplicate_type=duplicate_type,
        candidate_document_id=document.id,
        candidate_file_name=document.original_name,
        candidate_version=version.version if version else 1,
        score=score,
        distance=distance,
        threshold=threshold,
        reason=reason,
    )


def _dedupe_candidates(
    candidates: Iterable[DuplicateCandidate],
) -> list[DuplicateCandidate]:
    priority = {"exact": 0, "normalized": 1, "near": 2}
    best: dict[tuple[str, str], DuplicateCandidate] = {}
    for candidate in candidates:
        key = (candidate.duplicate_type, candidate.candidate_document_id)
        current = best.get(key)
        if current is None or priority[candidate.duplicate_type] < priority[current.duplicate_type]:
            best[key] = candidate
    return sorted(
        best.values(),
        key=lambda item: (
            priority.get(item.duplicate_type, 9),
            item.distance if item.distance is not None else 0,
            item.candidate_document_id,
        ),
    )


def _is_at_or_before(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return False
    current = now
    candidate = value
    if candidate.tzinfo is None and current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    if candidate.tzinfo is not None and current.tzinfo is None:
        candidate = candidate.replace(tzinfo=None)
    return candidate <= current
