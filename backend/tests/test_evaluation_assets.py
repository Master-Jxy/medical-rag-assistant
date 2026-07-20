import json
from pathlib import Path

from app.evaluation.corpus import (
    SourceChunk,
    SourceDocument,
    build_corpus_manifest,
    calculate_corpus_checksum,
)
from app.evaluation.schemas import CorpusManifest, EvaluationCategory, EvaluationSet

BACKEND_DIR = Path(__file__).resolve().parents[1]


def source_document(**overrides) -> SourceDocument:
    values = {
        "document_id": "document-1",
        "original_name": "document.txt",
        "stored_name": "document-1.txt",
        "registered_content_sha256": "a" * 64,
        "actual_content_sha256": "a" * 64,
        "size_bytes": 500,
        "actual_size_bytes": 500,
        "chunk_ids": ("document-1:0",),
    }
    values.update(overrides)
    return SourceDocument(**values)


def source_chunk(**overrides) -> SourceChunk:
    values = {
        "chunk_id": "document-1:0",
        "content": "有效知识片段" * 40,
        "metadata": {
            "document_id": "document-1",
            "file_hash": "a" * 64,
            "file_name": "document.txt",
        },
    }
    values.update(overrides)
    return SourceChunk(**values)


def build(documents=None, chunks=None):
    return build_corpus_manifest(
        documents=documents or [source_document()],
        chunks=chunks or [source_chunk()],
        generated_on="2026-07-18",
        chroma_collection="agent",
        chunk_size=800,
        chunk_overlap=100,
    )


def test_clean_manifest_is_deterministic_and_contains_no_chunk_body() -> None:
    manifest = build()
    assert manifest.audit_result.status == "passed"
    assert manifest.audit_result.consistency_passed is True
    assert manifest.corpus_checksum == calculate_corpus_checksum(manifest.documents)
    rendered = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False)
    assert "有效知识片段" not in rendered
    assert "content_sha256" in rendered


def test_audit_reports_consistency_failures_and_short_content() -> None:
    documents = [
        source_document(actual_content_sha256=None),
        source_document(
            document_id="document-2",
            original_name="copy.txt",
            stored_name="copy.txt",
            chunk_ids=("document-2:0",),
        ),
    ]
    chunks = [
        source_chunk(content="短"),
        source_chunk(
            chunk_id="orphan:0",
            content="",
            metadata={"document_id": "orphan"},
        ),
    ]
    manifest = build(documents, chunks)
    audit = manifest.audit_result
    assert audit.status == "failed"
    assert audit.consistency_passed is False
    assert audit.missing_file_document_ids == ["document-1"]
    assert audit.missing_chroma_chunk_ids == ["document-2:0"]
    assert audit.unregistered_chroma_chunk_ids == ["orphan:0"]
    assert audit.duplicate_document_hash_groups == [["document-1", "document-2"]]
    assert audit.short_chunk_ids == ["document-1:0"]


def test_checked_in_corpus_v1_and_evaluation_contract_are_valid() -> None:
    corpus_path = BACKEND_DIR / "evaluation" / "corpora" / "corpus_v1.json"
    manifest = CorpusManifest.model_validate_json(corpus_path.read_text(encoding="utf-8"))
    assert manifest.document_count == 27
    assert manifest.chunk_count == 103
    assert manifest.audit_result.consistency_passed is True
    assert manifest.corpus_checksum == calculate_corpus_checksum(manifest.documents)

    schema_path = BACKEND_DIR / "evaluation" / "schemas" / "evaluation_set_v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema == EvaluationSet.model_json_schema()
    assert schema["properties"]["cases"]["minItems"] == 30
    assert schema["properties"]["cases"]["maxItems"] == 50

    categories = json.loads(
        (BACKEND_DIR / "evaluation" / "categories_v1.json").read_text(encoding="utf-8")
    )
    category_ids = {item["id"] for item in categories["categories"]}
    assert category_ids == {item.value for item in EvaluationCategory}
    assert sum(item["target_count"] for item in categories["categories"]) == 40
    assert categories["target_case_count"] == 40

    generated_schema = EvaluationSet.model_json_schema()
    assert generated_schema["properties"]["cases"]["minItems"] == 30
