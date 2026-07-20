"""用纯数据构建可复现的语料清单，不读取模型或线上会话。"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

from app.evaluation.schemas import (
    CorpusAuditPolicy,
    CorpusAuditResult,
    CorpusChunkEntry,
    CorpusDocumentEntry,
    CorpusManifest,
)


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    original_name: str
    stored_name: str
    registered_content_sha256: str
    actual_content_sha256: str | None
    size_bytes: int
    actual_size_bytes: int | None
    chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    content: str
    metadata: dict[str, Any]


def normalize_chunk_content(content: str) -> str:
    return " ".join(content.split())


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def calculate_corpus_checksum(documents: Sequence[CorpusDocumentEntry]) -> str:
    payload = [document.model_dump(mode="json") for document in documents]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(canonical)


def build_corpus_manifest(
    *,
    documents: Sequence[SourceDocument],
    chunks: Sequence[SourceChunk],
    generated_on: str,
    chroma_collection: str,
    chunk_size: int,
    chunk_overlap: int,
    short_document_chars_lt: int = 200,
    short_chunk_chars_lt: int = 50,
) -> CorpusManifest:
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    registered_chunk_ids = [chunk_id for item in documents for chunk_id in item.chunk_ids]
    registered_set = set(registered_chunk_ids)
    chroma_set = set(chunk_by_id)

    missing_files: list[str] = []
    hash_mismatches: list[str] = []
    size_mismatches: list[str] = []
    empty_documents: list[str] = []
    short_documents: list[str] = []
    empty_chunks: list[str] = []
    short_chunks: list[str] = []
    metadata_mismatches: list[str] = []
    file_hash_groups: dict[str, list[str]] = defaultdict(list)
    chunk_hash_groups: dict[str, list[str]] = defaultdict(list)
    manifest_documents: list[CorpusDocumentEntry] = []

    for document in sorted(documents, key=lambda item: (item.original_name, item.document_id)):
        file_hash_groups[document.registered_content_sha256].append(document.document_id)
        if document.actual_content_sha256 is None:
            missing_files.append(document.document_id)
        elif document.actual_content_sha256 != document.registered_content_sha256:
            hash_mismatches.append(document.document_id)
        if (
            document.actual_size_bytes is not None
            and document.actual_size_bytes != document.size_bytes
        ):
            size_mismatches.append(document.document_id)

        document_chunks: list[CorpusChunkEntry] = []
        total_chars = 0
        for chunk_id in document.chunk_ids:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            normalized = normalize_chunk_content(chunk.content)
            content_hash = _sha256_text(normalized)
            char_count = len(normalized)
            total_chars += char_count
            chunk_hash_groups[content_hash].append(chunk_id)
            if char_count == 0:
                empty_chunks.append(chunk_id)
            elif char_count < short_chunk_chars_lt:
                short_chunks.append(chunk_id)
            if (
                chunk.metadata.get("document_id") != document.document_id
                or chunk.metadata.get("file_hash") != document.registered_content_sha256
                or chunk.metadata.get("file_name") != document.original_name
            ):
                metadata_mismatches.append(chunk_id)
            document_chunks.append(
                CorpusChunkEntry(
                    chunk_id=chunk_id,
                    content_sha256=content_hash,
                    normalized_char_count=char_count,
                )
            )
        if total_chars == 0:
            empty_documents.append(document.document_id)
        elif total_chars < short_document_chars_lt:
            short_documents.append(document.document_id)
        manifest_documents.append(
            CorpusDocumentEntry(
                document_id=document.document_id,
                original_name=document.original_name,
                stored_name=document.stored_name,
                content_sha256=document.registered_content_sha256,
                size_bytes=document.size_bytes,
                chunk_count=len(document.chunk_ids),
                chunks=document_chunks,
            )
        )

    duplicate_document_groups = sorted(
        sorted(ids) for ids in file_hash_groups.values() if len(ids) > 1
    )
    duplicate_chunk_groups = sorted(
        sorted(ids) for ids in chunk_hash_groups.values() if len(ids) > 1
    )
    missing_chroma = sorted(registered_set - chroma_set)
    unregistered_chroma = sorted(chroma_set - registered_set)
    registered_id_groups: dict[str, int] = defaultdict(int)
    for chunk_id in registered_chunk_ids:
        registered_id_groups[chunk_id] += 1
    duplicate_registered_ids = sorted(
        chunk_id for chunk_id, count in registered_id_groups.items() if count > 1
    )
    consistency_passed = not any(
        (
            missing_files,
            hash_mismatches,
            size_mismatches,
            missing_chroma,
            unregistered_chroma,
            duplicate_document_groups,
            duplicate_chunk_groups,
            empty_documents,
            empty_chunks,
            metadata_mismatches,
            duplicate_registered_ids,
        )
    )
    has_warnings = bool(short_documents or short_chunks)
    status = "failed" if not consistency_passed else "passed_with_warnings" if has_warnings else "passed"

    return CorpusManifest(
        schema_version="corpus_manifest_v1",
        corpus_version="corpus_v1",
        generated_on=generated_on,
        checksum_algorithm="sha256",
        corpus_checksum=calculate_corpus_checksum(manifest_documents),
        chroma_collection=chroma_collection,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        document_count=len(manifest_documents),
        chunk_count=len(registered_chunk_ids),
        audit_policy=CorpusAuditPolicy(
            empty_content_normalization="collapse_whitespace",
            short_document_chars_lt=short_document_chars_lt,
            short_chunk_chars_lt=short_chunk_chars_lt,
        ),
        audit_result=CorpusAuditResult(
            status=status,
            consistency_passed=consistency_passed,
            missing_file_document_ids=sorted(missing_files),
            file_hash_mismatch_document_ids=sorted(hash_mismatches),
            file_size_mismatch_document_ids=sorted(size_mismatches),
            missing_chroma_chunk_ids=missing_chroma,
            unregistered_chroma_chunk_ids=unregistered_chroma,
            duplicate_registered_chunk_ids=duplicate_registered_ids,
            duplicate_document_hash_groups=duplicate_document_groups,
            duplicate_chunk_content_groups=duplicate_chunk_groups,
            empty_document_ids=sorted(empty_documents),
            empty_chunk_ids=sorted(empty_chunks),
            short_document_ids=sorted(short_documents),
            short_chunk_ids=sorted(short_chunks),
            metadata_mismatch_chunk_ids=sorted(metadata_mismatches),
        ),
        documents=manifest_documents,
    )
