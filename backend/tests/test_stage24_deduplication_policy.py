"""Stage 24.6 duplicate fingerprint policy tests."""

import hashlib

from app.modules.knowledge.deduplication import (
    MAX_NORMALIZED_TEXT_CHARS,
    NEAR_DUPLICATE_SCAN_LIMIT,
    DuplicateCandidateService,
    DuplicatePolicy,
    hamming_distance,
    normalize_text,
)
from app.db.base import Base
from app.db.session import build_engine
from app.models import DocumentVersion, KnowledgeDocument
from sqlalchemy.orm import Session


def test_normalized_hash_is_versioned_and_stable_for_whitespace_and_width() -> None:
    left = DuplicatePolicy.fingerprint_text("糖尿病  指南\nA１")
    right = DuplicatePolicy.fingerprint_text("糖尿病 指南 A1")

    assert left.normalized_text_hash == right.normalized_text_hash
    assert left.normalized_text_hash_version == "normalized_text_sha256_v1"
    assert left.near_duplicate_fingerprint_version == "simhash64_v1"


def test_normalization_has_a_deterministic_resource_cap() -> None:
    text = "表格 行 " * (MAX_NORMALIZED_TEXT_CHARS // 3)
    normalized = normalize_text(text)

    assert len(normalized) <= MAX_NORMALIZED_TEXT_CHARS
    assert "\x00" not in normalize_text("abc\x00def")


def test_near_duplicate_simhash_separates_close_and_distant_text() -> None:
    baseline = DuplicatePolicy.fingerprint_text("心力衰竭 随访 用药 复查 血压 心率")
    close = DuplicatePolicy.fingerprint_text("心力衰竭 随访 用药 复查 血压")
    distant = DuplicatePolicy.fingerprint_text("糖尿病 饮食 胰岛素 血糖 足部护理")

    assert hamming_distance(
        int(baseline.near_duplicate_fingerprint, 16),
        int(close.near_duplicate_fingerprint, 16),
    ) < hamming_distance(
        int(baseline.near_duplicate_fingerprint, 16),
        int(distant.near_duplicate_fingerprint, 16),
    )


def _document(document_id: str, text: str, *, fingerprint: str | None = None):
    computed = DuplicatePolicy.fingerprint_text(text)
    return (
        KnowledgeDocument(
            id=document_id,
            original_name=f"{document_id}.txt",
            stored_name=f"{document_id}.txt",
            content_hash=hashlib.sha256(document_id.encode("utf-8")).hexdigest(),
            size_bytes=10,
            chunk_count=1,
            chunk_ids=[f"{document_id}:0"],
            uploader_id=None,
            is_system=True,
            status="published",
        ),
        DocumentVersion(
            id=f"version-{document_id}",
            document_id=document_id,
            version=1,
            source="system",
            tags=[],
            normalized_text_hash=computed.normalized_text_hash,
            normalized_text_hash_version=computed.normalized_text_hash_version,
            near_duplicate_fingerprint=(
                fingerprint if fingerprint is not None else computed.near_duplicate_fingerprint
            ),
            near_duplicate_fingerprint_version=computed.near_duplicate_fingerprint_version,
        ),
    )


def test_near_duplicate_query_has_hard_limit_and_ignores_invalid_hex() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        target_doc, target_version = _document("doc-target", "心力衰竭 随访 用药 血压")
        session.add_all([target_doc, target_version])
        invalid_doc, invalid_version = _document(
            "doc-invalid",
            "心力衰竭 随访 用药 血压",
            fingerprint="not-a-hex-value",
        )
        session.add_all([invalid_doc, invalid_version])
        for index in range(NEAR_DUPLICATE_SCAN_LIMIT + 5):
            document, version = _document(
                f"doc-{index:03d}",
                f"心力衰竭 随访 用药 血压 {index}",
            )
            session.add_all([document, version])
        session.commit()

        candidates = DuplicateCandidateService(session).for_document(
            target_doc,
            target_version,
            limit=NEAR_DUPLICATE_SCAN_LIMIT + 10,
        )

        near = [candidate for candidate in candidates if candidate.duplicate_type == "near"]
        assert len(near) <= NEAR_DUPLICATE_SCAN_LIMIT
        assert all(candidate.candidate_document_id != "doc-invalid" for candidate in near)

        target_version.near_duplicate_fingerprint = "bad"
        target_version.normalized_text_hash = None
        target_version.normalized_text_hash_version = None
        assert DuplicateCandidateService(session).for_document(target_doc, target_version) == []
    engine.dispose()
