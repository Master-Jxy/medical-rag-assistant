"""版本化语料清单与评估集的数据契约。"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorpusChunkEntry(StrictModel):
    chunk_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_char_count: int = Field(ge=0)


class CorpusDocumentEntry(StrictModel):
    document_id: str
    original_name: str
    stored_name: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    chunk_count: int = Field(gt=0)
    chunks: list[CorpusChunkEntry]

    @model_validator(mode="after")
    def chunk_count_matches_entries(self) -> "CorpusDocumentEntry":
        if self.chunk_count < len(self.chunks):
            raise ValueError("chunks 数量不能超过登记的 chunk_count")
        return self


class CorpusAuditPolicy(StrictModel):
    empty_content_normalization: Literal["collapse_whitespace"]
    short_document_chars_lt: int = Field(gt=0)
    short_chunk_chars_lt: int = Field(gt=0)


class CorpusAuditResult(StrictModel):
    status: Literal["passed", "passed_with_warnings", "failed"]
    consistency_passed: bool
    missing_file_document_ids: list[str]
    file_hash_mismatch_document_ids: list[str]
    file_size_mismatch_document_ids: list[str]
    missing_chroma_chunk_ids: list[str]
    unregistered_chroma_chunk_ids: list[str]
    duplicate_registered_chunk_ids: list[str]
    duplicate_document_hash_groups: list[list[str]]
    duplicate_chunk_content_groups: list[list[str]]
    empty_document_ids: list[str]
    empty_chunk_ids: list[str]
    short_document_ids: list[str]
    short_chunk_ids: list[str]
    metadata_mismatch_chunk_ids: list[str]


class CorpusManifest(StrictModel):
    schema_version: Literal["corpus_manifest_v1"]
    corpus_version: Literal["corpus_v1"]
    generated_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    checksum_algorithm: Literal["sha256"]
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    chroma_collection: str
    chunk_size: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    audit_policy: CorpusAuditPolicy
    audit_result: CorpusAuditResult
    documents: list[CorpusDocumentEntry]

    @model_validator(mode="after")
    def totals_match_entries(self) -> "CorpusManifest":
        if self.document_count != len(self.documents):
            raise ValueError("document_count 必须与 documents 数量一致")
        if self.chunk_count != sum(item.chunk_count for item in self.documents):
            raise ValueError("chunk_count 必须与文档片段数量之和一致")
        return self


class EvaluationCategory(StrEnum):
    SINGLE_DOCUMENT = "single_document"
    MULTI_DOCUMENT = "multi_document"
    CONVERSATIONAL_FOLLOW_UP = "conversational_follow_up"
    INSUFFICIENT_KNOWLEDGE = "insufficient_knowledge"
    SAFETY_BOUNDARY = "safety_boundary"


class ExpectedBehavior(StrEnum):
    ANSWER = "answer"
    REFUSE = "refuse"


class EvaluationHistoryTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class EvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^eval_[0-9]{3}$")
    category: EvaluationCategory
    question: str = Field(min_length=1)
    history: list[EvaluationHistoryTurn] = Field(default_factory=list)
    expected_behavior: ExpectedBehavior
    expected_source_document_ids: list[str]
    expected_key_facts: list[str]
    tags: list[str] = Field(default_factory=list)


class EvaluationSet(StrictModel):
    schema_version: Literal["evaluation_set_v1"]
    dataset_version: str = Field(pattern=r"^eval_v[0-9]+$")
    corpus_version: Literal["corpus_v1"]
    corpus_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[EvaluationCase] = Field(min_length=30, max_length=50)
