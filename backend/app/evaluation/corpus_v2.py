"""Corpus v2 manifest, evaluation set, and no-cost preflight contracts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.knowledge.deduplication import (
    NEAR_DUPLICATE_DISTANCE_THRESHOLD,
    NEAR_DUPLICATE_FINGERPRINT_VERSION,
    NORMALIZED_TEXT_HASH_VERSION,
    hamming_distance,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
DOCUMENT_ID_PATTERN = r"^cv2_[a-z0-9_]+$"
CASE_ID_PATTERN = r"^eval2_[0-9]{3}$"

CORPUS_V2_MANIFEST_VERSION = "corpus_manifest_v2"
CORPUS_V2_VERSION = "corpus_v2"
EVALUATION_SET_V2_VERSION = "evaluation_set_v2"
DATASET_V2_VERSION = "eval_v2"

MATRIX_REQUIREMENTS: dict[str, int] = {
    "basic_fact": 2,
    "multi_source": 2,
    "table": 2,
    "scan_ocr": 2,
    "image_vision": 2,
    "refusal": 2,
    "version_conflict": 2,
    "duplicate": 1,
    "multi_format": 4,
    "web_snapshot": 1,
}

ZERO_PROVIDER_CALLS = {
    "embedding_calls": 0,
    "llm_calls": 0,
    "rerank_calls": 0,
    "ocr_calls": 0,
    "vision_calls": 0,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParserExpectation(StrictModel):
    parser_name: str = Field(min_length=1, max_length=80)
    parser_version: str = Field(min_length=1, max_length=80)
    requires_ocr: bool = False
    requires_vision: bool = False


class CorpusV2Governance(StrictModel):
    status: Literal["current", "due", "expired", "pending_review"]
    review_due_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class CorpusV2Document(StrictModel):
    id: str = Field(pattern=DOCUMENT_ID_PATTERN)
    file_name: str = Field(min_length=1, max_length=255)
    relative_path: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=500)
    source_organization: str = Field(min_length=1, max_length=200)
    license: str = Field(min_length=1, max_length=200)
    usage_boundary: str = Field(min_length=1, max_length=500)
    publication_date: str = Field(pattern=r"^(\d{4}-\d{2}-\d{2}|unknown)$")
    fetched_at: str = Field(pattern=r"^(\d{4}-\d{2}-\d{2}|pending_review)$")
    department: str = Field(min_length=1, max_length=100)
    disease_topics: list[str] = Field(min_length=1)
    document_type: Literal[
        "pdf",
        "docx",
        "markdown",
        "html",
        "web_snapshot",
        "image",
        "txt",
    ]
    language: Literal["zh-CN", "en", "unknown"]
    content_sha256: str = Field(pattern=rf"^({SHA256_PATTERN[1:-1]}|unknown)$")
    normalized_text_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    near_duplicate_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{16}$",
    )
    parser_expected: ParserExpectation
    has_table: bool = False
    has_scanned_pages: bool = False
    has_images: bool = False
    governance: CorpusV2Governance
    ingestion_status: Literal["fixture_placeholder", "pending_review", "ready"]
    estimated_pages_min: int = Field(ge=0)
    estimated_pages_max: int = Field(ge=0)
    estimated_chunks_min: int = Field(ge=0)
    estimated_chunks_max: int = Field(ge=0)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_boundaries(self) -> "CorpusV2Document":
        if Path(self.relative_path).is_absolute() or ".." in Path(self.relative_path).parts:
            raise ValueError("relative_path must be repository-relative and non-traversing")
        if self.estimated_pages_max < self.estimated_pages_min:
            raise ValueError("estimated_pages_max must be >= estimated_pages_min")
        if self.estimated_chunks_max < self.estimated_chunks_min:
            raise ValueError("estimated_chunks_max must be >= estimated_chunks_min")
        if self.ingestion_status != "ready" and self.content_sha256 != "unknown":
            raise ValueError("non-ready documents must not claim a concrete content hash")
        if self.ingestion_status == "ready" and self.content_sha256 == "unknown":
            raise ValueError("ready documents require a content hash")
        if self.license == "unknown" and self.governance.status != "pending_review":
            raise ValueError("unknown license requires pending_review governance")
        return self


class CorpusV2Manifest(StrictModel):
    schema_version: Literal["corpus_manifest_v2"]
    corpus_version: Literal["corpus_v2"]
    generated_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    checksum_algorithm: Literal["sha256"]
    corpus_checksum: str = Field(pattern=SHA256_PATTERN)
    prior_corpus_version: Literal["corpus_v1"]
    overwrite_policy: Literal["never_overwrite_corpus_v1"]
    document_count: int = Field(ge=0)
    documents: list[CorpusV2Document]
    intake_policy: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def totals_and_checksum_match(self) -> "CorpusV2Manifest":
        if self.document_count != len(self.documents):
            raise ValueError("document_count must match documents length")
        expected = calculate_corpus_v2_checksum(self.documents)
        if self.corpus_checksum != expected:
            raise ValueError("corpus_checksum mismatch")
        return self


class EvidenceReference(StrictModel):
    document_id: str = Field(pattern=DOCUMENT_ID_PATTERN)
    evidence_key: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=300)


class EvaluationCaseV2(StrictModel):
    case_id: str = Field(pattern=CASE_ID_PATTERN)
    category: Literal[
        "basic_fact",
        "multi_source",
        "table",
        "scan_ocr",
        "image_vision",
        "refusal",
        "version_conflict",
    ]
    question: str = Field(min_length=1, max_length=500)
    expected_behavior: Literal["answer", "refuse", "blocked"]
    expected_source_document_ids: list[str]
    expected_evidence: list[EvidenceReference]
    scoring_rules: list[str] = Field(min_length=1)
    requires_external_provider: bool = False
    blocked_reason: str | None = Field(default=None, max_length=300)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def blocked_cases_are_explicit(self) -> "EvaluationCaseV2":
        if self.expected_behavior == "blocked" and not self.blocked_reason:
            raise ValueError("blocked cases require blocked_reason")
        if self.expected_behavior != "blocked" and self.blocked_reason:
            raise ValueError("only blocked cases may set blocked_reason")
        if self.expected_behavior == "refuse" and self.expected_source_document_ids:
            raise ValueError("refusal cases must not claim source documents")
        if self.requires_external_provider and self.expected_behavior != "blocked":
            raise ValueError("provider-dependent cases must stay blocked in stage 24.7")
        return self


class EvaluationSetV2(StrictModel):
    schema_version: Literal["evaluation_set_v2"]
    dataset_version: Literal["eval_v2"]
    corpus_version: Literal["corpus_v2"]
    corpus_checksum: str = Field(pattern=SHA256_PATTERN)
    cases: list[EvaluationCaseV2] = Field(min_length=1, max_length=80)


class CoverageItem(StrictModel):
    id: str
    minimum: int = Field(ge=0)
    planned_count: int = Field(ge=0)
    current_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    gap: int = Field(ge=0)
    evidence_document_ids: list[str]
    planned_document_ids: list[str]
    executable_case_ids: list[str]
    blocked_case_ids: list[str]


class CoverageMatrix(StrictModel):
    schema_version: Literal["corpus_v2_coverage_matrix_v1"]
    corpus_version: Literal["corpus_v2"]
    corpus_checksum: str = Field(pattern=SHA256_PATTERN)
    items: list[CoverageItem]
    gaps: list[str]


class DedupSignalGroup(StrictModel):
    signal: Literal["exact", "normalized", "near"]
    document_ids: list[str] = Field(min_length=2)
    reason: str
    distance: int | None = None
    threshold: int | None = None


class CleaningDedupReport(StrictModel):
    schema_version: Literal["corpus_v2_cleaning_dedup_report_v1"]
    corpus_version: Literal["corpus_v2"]
    corpus_checksum: str = Field(pattern=SHA256_PATTERN)
    generated_from: Literal["manifest_metadata_only"]
    algorithms: dict[str, str | int]
    exact_duplicate_groups: list[DedupSignalGroup]
    normalized_duplicate_groups: list[DedupSignalGroup]
    near_duplicate_hints: list[DedupSignalGroup]
    skipped_unknown_content_ids: list[str]
    warnings: list[str]
    auto_deleted: Literal[False]


class ProviderCallBudget(StrictModel):
    embedding_calls: int = 0
    llm_calls: int = 0
    rerank_calls: int = 0
    ocr_calls: int = 0
    vision_calls: int = 0


class CorpusV2PreflightSummary(StrictModel):
    schema_version: Literal["corpus_v2_no_cost_preflight_v1"]
    corpus_version: Literal["corpus_v2"]
    corpus_checksum: str = Field(pattern=SHA256_PATTERN)
    dataset_version: Literal["eval_v2"]
    document_count: int = Field(ge=0)
    blocked_case_count: int = Field(ge=0)
    coverage_gap_count: int = Field(ge=0)
    estimated_pages_min: int = Field(ge=0)
    estimated_pages_max: int = Field(ge=0)
    estimated_chunks_min: int = Field(ge=0)
    estimated_chunks_max: int = Field(ge=0)
    estimated_embedding_token_upper_bound: int = Field(ge=0)
    estimated_embedding_cost_cny_upper_bound: float = Field(ge=0)
    provider_calls: ProviderCallBudget
    would_require_provider_calls_after_approval: ProviderCallBudget
    validation_warnings: list[str]
    no_cost_gate_passed: bool


@dataclass(frozen=True)
class CorpusV2ValidationSummary:
    document_count: int
    case_count: int
    blocked_case_count: int
    warnings: tuple[str, ...]


def canonical_sha256(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def calculate_corpus_v2_checksum(documents: list[CorpusV2Document]) -> str:
    payload = [item.model_dump(mode="json") for item in sorted(documents, key=lambda d: d.id)]
    return canonical_sha256(payload)


def load_manifest(path: Path) -> CorpusV2Manifest:
    return CorpusV2Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_evaluation_set(path: Path) -> EvaluationSetV2:
    return EvaluationSetV2.model_validate_json(path.read_text(encoding="utf-8"))


def validate_corpus_v2_assets(
    manifest: CorpusV2Manifest,
    evaluation_set: EvaluationSetV2,
) -> CorpusV2ValidationSummary:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.corpus_version == "corpus_v1":
        errors.append("corpus_v2 manifest must not use corpus_v1")
    if evaluation_set.corpus_version != manifest.corpus_version:
        errors.append("evaluation_set corpus_version mismatch")
    if evaluation_set.corpus_checksum != manifest.corpus_checksum:
        errors.append("evaluation_set corpus_checksum mismatch")

    document_ids = [document.id for document in manifest.documents]
    duplicate_ids = sorted(id_ for id_, count in Counter(document_ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate document id: {duplicate_ids}")
    relative_paths = [document.relative_path for document in manifest.documents]
    duplicate_paths = sorted(path for path, count in Counter(relative_paths).items() if count > 1)
    if duplicate_paths:
        errors.append(f"duplicate relative_path: {duplicate_paths}")

    known_document_ids = set(document_ids)
    case_ids = [case.case_id for case in evaluation_set.cases]
    duplicate_case_ids = sorted(id_ for id_, count in Counter(case_ids).items() if count > 1)
    if duplicate_case_ids:
        errors.append(f"duplicate case id: {duplicate_case_ids}")
    expected_case_ids = [f"eval2_{index:03d}" for index in range(1, len(case_ids) + 1)]
    if case_ids != expected_case_ids:
        errors.append("eval2 case ids must be sequential")

    for document in manifest.documents:
        if document.license == "unknown":
            warnings.append(f"{document.id}: license unknown")
        if document.source_url == "unknown":
            warnings.append(f"{document.id}: source URL pending review")
        if document.content_sha256 == "unknown":
            warnings.append(f"{document.id}: content hash pending review")

    for case in evaluation_set.cases:
        source_ids = set(case.expected_source_document_ids)
        evidence_ids = {item.document_id for item in case.expected_evidence}
        unknown = sorted((source_ids | evidence_ids) - known_document_ids)
        if unknown:
            errors.append(f"{case.case_id}: references unknown documents {unknown}")
        if case.expected_behavior == "answer" and not source_ids:
            errors.append(f"{case.case_id}: answer case requires sources")
        if case.expected_behavior == "blocked":
            warnings.append(f"{case.case_id}: blocked ({case.blocked_reason})")

    if errors:
        raise ValueError("; ".join(errors))
    return CorpusV2ValidationSummary(
        document_count=len(manifest.documents),
        case_count=len(evaluation_set.cases),
        blocked_case_count=sum(
            1 for case in evaluation_set.cases if case.expected_behavior == "blocked"
        ),
        warnings=tuple(sorted(warnings)),
    )


def build_coverage_matrix(
    manifest: CorpusV2Manifest,
    evaluation_set: EvaluationSetV2,
) -> CoverageMatrix:
    planned_document_ids_by_need: dict[str, set[str]] = defaultdict(set)
    ready_document_ids_by_need: dict[str, set[str]] = defaultdict(set)
    for document in manifest.documents:
        planned_document_ids_by_need["basic_fact"].add(document.id)
        planned_document_ids_by_need["multi_format"].add(document.id)
        if _is_ready_document(document):
            ready_document_ids_by_need["basic_fact"].add(document.id)
            ready_document_ids_by_need["multi_format"].add(document.id)
        if document.has_table:
            planned_document_ids_by_need["table"].add(document.id)
            if _is_ready_document(document):
                ready_document_ids_by_need["table"].add(document.id)
        if document.has_scanned_pages:
            planned_document_ids_by_need["scan_ocr"].add(document.id)
            if _is_ready_document(document):
                ready_document_ids_by_need["scan_ocr"].add(document.id)
        if document.has_images:
            planned_document_ids_by_need["image_vision"].add(document.id)
            if _is_ready_document(document):
                ready_document_ids_by_need["image_vision"].add(document.id)
        if document.document_type == "web_snapshot":
            planned_document_ids_by_need["web_snapshot"].add(document.id)
            if _is_ready_document(document):
                ready_document_ids_by_need["web_snapshot"].add(document.id)
    planned_case_ids_by_category: dict[str, set[str]] = defaultdict(set)
    executable_case_ids_by_category: dict[str, set[str]] = defaultdict(set)
    blocked_by_category: dict[str, set[str]] = defaultdict(set)
    for case in evaluation_set.cases:
        planned_case_ids_by_category[case.category].add(case.case_id)
        if case.expected_behavior != "blocked":
            executable_case_ids_by_category[case.category].add(case.case_id)
        if case.expected_behavior == "blocked":
            blocked_by_category[case.category].add(case.case_id)
        if "duplicate" in case.tags:
            planned_case_ids_by_category["duplicate"].add(case.case_id)
            if case.expected_behavior != "blocked":
                executable_case_ids_by_category["duplicate"].add(case.case_id)
            if case.expected_behavior == "blocked":
                blocked_by_category["duplicate"].add(case.case_id)

    items: list[CoverageItem] = []
    gaps: list[str] = []
    for key, minimum in MATRIX_REQUIREMENTS.items():
        if key in {"multi_source", "refusal", "version_conflict", "duplicate"}:
            planned = len(planned_case_ids_by_category.get(key, set()))
            executable_case_ids = sorted(executable_case_ids_by_category.get(key, set()))
            current = len(executable_case_ids)
            blocked = len(blocked_by_category.get(key, set()))
            evidence_ids: list[str] = []
            planned_document_ids: list[str] = []
        else:
            planned_document_ids = sorted(planned_document_ids_by_need.get(key, set()))
            evidence_ids = sorted(ready_document_ids_by_need.get(key, set()))
            planned = len(planned_document_ids)
            current = len(evidence_ids)
            blocked = max(0, planned - current)
            executable_case_ids = []
        gap = max(0, minimum - current)
        if gap:
            gaps.append(key)
        items.append(
            CoverageItem(
                id=key,
                minimum=minimum,
                planned_count=planned,
                current_count=current,
                blocked_count=blocked,
                gap=gap,
                evidence_document_ids=evidence_ids,
                planned_document_ids=planned_document_ids,
                executable_case_ids=executable_case_ids,
                blocked_case_ids=sorted(blocked_by_category.get(key, set())),
            )
        )
    return CoverageMatrix(
        schema_version="corpus_v2_coverage_matrix_v1",
        corpus_version=manifest.corpus_version,
        corpus_checksum=manifest.corpus_checksum,
        items=items,
        gaps=gaps,
    )


def build_cleaning_dedup_report(manifest: CorpusV2Manifest) -> CleaningDedupReport:
    exact_groups = _hash_groups(
        [
            (document.content_sha256, document.id)
            for document in manifest.documents
            if document.content_sha256 != "unknown"
        ],
        "exact",
        "原始文件 bytes SHA-256 相同",
    )
    normalized_groups = _hash_groups(
        [
            (document.normalized_text_sha256, document.id)
            for document in manifest.documents
            if document.normalized_text_sha256
        ],
        "normalized",
        "规范化正文 SHA-256 相同",
    )
    near_hints: list[DedupSignalGroup] = []
    docs_with_fingerprint = [
        document
        for document in manifest.documents
        if document.near_duplicate_fingerprint
    ]
    for index, left in enumerate(docs_with_fingerprint):
        for right in docs_with_fingerprint[index + 1 :]:
            distance = hamming_distance(
                int(left.near_duplicate_fingerprint or "0", 16),
                int(right.near_duplicate_fingerprint or "0", 16),
            )
            if distance <= NEAR_DUPLICATE_DISTANCE_THRESHOLD:
                near_hints.append(
                    DedupSignalGroup(
                        signal="near",
                        document_ids=sorted([left.id, right.id]),
                        reason="近重复 SimHash 距离低于阈值",
                        distance=distance,
                        threshold=NEAR_DUPLICATE_DISTANCE_THRESHOLD,
                    )
                )
    warnings = [
        "content unavailable: exact/normalized signals remain pending"
        for document in manifest.documents
        if document.content_sha256 == "unknown"
    ]
    return CleaningDedupReport(
        schema_version="corpus_v2_cleaning_dedup_report_v1",
        corpus_version=manifest.corpus_version,
        corpus_checksum=manifest.corpus_checksum,
        generated_from="manifest_metadata_only",
        algorithms={
            "exact": "bytes_sha256",
            "normalized": NORMALIZED_TEXT_HASH_VERSION,
            "near": NEAR_DUPLICATE_FINGERPRINT_VERSION,
            "near_threshold": NEAR_DUPLICATE_DISTANCE_THRESHOLD,
        },
        exact_duplicate_groups=exact_groups,
        normalized_duplicate_groups=normalized_groups,
        near_duplicate_hints=sorted(
            near_hints,
            key=lambda item: (item.distance or 0, item.document_ids),
        ),
        skipped_unknown_content_ids=sorted(
            document.id
            for document in manifest.documents
            if document.content_sha256 == "unknown"
        ),
        warnings=sorted(set(warnings)),
        auto_deleted=False,
    )


def build_preflight_summary(
    manifest: CorpusV2Manifest,
    evaluation_set: EvaluationSetV2,
    coverage: CoverageMatrix,
    provider_calls: ProviderCallBudget | None = None,
    execute_provider_calls: bool = False,
) -> CorpusV2PreflightSummary:
    validation = validate_corpus_v2_assets(manifest, evaluation_set)
    pages_min = sum(document.estimated_pages_min for document in manifest.documents)
    pages_max = sum(document.estimated_pages_max for document in manifest.documents)
    chunks_min = sum(document.estimated_chunks_min for document in manifest.documents)
    chunks_max = sum(document.estimated_chunks_max for document in manifest.documents)
    provider_after_approval = ProviderCallBudget(
        embedding_calls=chunks_max,
        ocr_calls=sum(1 for document in manifest.documents if document.has_scanned_pages),
        vision_calls=sum(1 for document in manifest.documents if document.has_images),
        rerank_calls=len(evaluation_set.cases),
        llm_calls=sum(
            1 for case in evaluation_set.cases if case.expected_behavior != "blocked"
        ),
    )
    embedding_tokens = chunks_max * 1_000
    current_provider_calls = provider_calls or ProviderCallBudget(**ZERO_PROVIDER_CALLS)
    return CorpusV2PreflightSummary(
        schema_version="corpus_v2_no_cost_preflight_v1",
        corpus_version=manifest.corpus_version,
        corpus_checksum=manifest.corpus_checksum,
        dataset_version=evaluation_set.dataset_version,
        document_count=manifest.document_count,
        blocked_case_count=validation.blocked_case_count,
        coverage_gap_count=len(coverage.gaps),
        estimated_pages_min=pages_min,
        estimated_pages_max=pages_max,
        estimated_chunks_min=chunks_min,
        estimated_chunks_max=chunks_max,
        estimated_embedding_token_upper_bound=embedding_tokens,
        estimated_embedding_cost_cny_upper_bound=round(embedding_tokens * 0.0007 / 1000, 6),
        provider_calls=current_provider_calls,
        would_require_provider_calls_after_approval=provider_after_approval,
        validation_warnings=list(validation.warnings),
        no_cost_gate_passed=is_no_cost_gate_passed(
            current_provider_calls,
            execute_provider_calls=execute_provider_calls,
        ),
    )


def render_preflight_markdown(summary: CorpusV2PreflightSummary) -> str:
    calls = summary.provider_calls.model_dump()
    would = summary.would_require_provider_calls_after_approval.model_dump()
    lines = [
        "# corpus_v2 no-cost preflight",
        "",
        f"- corpus: `{summary.corpus_version}`",
        f"- checksum: `{summary.corpus_checksum}`",
        f"- documents: {summary.document_count}",
        f"- blocked cases: {summary.blocked_case_count}",
        f"- coverage gaps: {summary.coverage_gap_count}",
        f"- estimated pages: {summary.estimated_pages_min}-{summary.estimated_pages_max}",
        f"- estimated chunks: {summary.estimated_chunks_min}-{summary.estimated_chunks_max}",
        f"- real provider calls now: {calls}",
        f"- provider calls after future approval: {would}",
        f"- no-cost gate: {summary.no_cost_gate_passed}",
    ]
    if summary.validation_warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in summary.validation_warnings)
    return "\n".join(lines) + "\n"


def _hash_groups(
    pairs: list[tuple[str | None, str]],
    signal: Literal["exact", "normalized"],
    reason: str,
) -> list[DedupSignalGroup]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for digest, document_id in pairs:
        if digest:
            grouped[digest].append(document_id)
    return [
        DedupSignalGroup(
            signal=signal,
            document_ids=sorted(ids),
            reason=reason,
        )
        for ids in grouped.values()
        if len(ids) > 1
    ]


def _is_ready_document(document: CorpusV2Document) -> bool:
    return (
        document.ingestion_status == "ready"
        and document.governance.status == "current"
        and document.content_sha256 != "unknown"
    )


def is_no_cost_gate_passed(
    provider_calls: ProviderCallBudget,
    *,
    execute_provider_calls: bool,
) -> bool:
    return not execute_provider_calls and not any(provider_calls.model_dump().values())
