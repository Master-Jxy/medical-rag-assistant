"""Metadata suggestion governance contracts and application service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.audit.ports import AuditPort, AuditRecord
from app.modules.knowledge.models import (
    DocumentVersion,
    KnowledgeSubmission,
    MetadataSuggestion,
)

METADATA_FIELDS = {
    "department",
    "disease_topics",
    "document_type",
    "published_year",
    "source",
    "review_due_at",
}
MAX_EVIDENCE_ITEMS = 8
MAX_EVIDENCE_SNIPPET_CHARS = 240
MAX_WARNING_ITEMS = 12
MAX_WARNING_CHARS = 200
ALLOWED_SUGGESTION_SOURCES = {"disabled", "fake", "manual"}


class MetadataSuggestionConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "metadata suggestion has already been reviewed",
            code="METADATA_SUGGESTION_CONFLICT",
            status_code=409,
        )


class MetadataSuggestionNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "metadata suggestion was not found",
            code="METADATA_SUGGESTION_NOT_FOUND",
            status_code=404,
        )


class MetadataSuggestionModeError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "unsupported metadata suggestion mode",
            code="METADATA_SUGGESTION_MODE_INVALID",
            status_code=500,
        )


class MetadataFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department: str | None = Field(default=None, max_length=100)
    disease_topics: list[str] = Field(default_factory=list, max_length=20)
    document_type: str | None = Field(default=None, max_length=80)
    published_year: int | None = Field(default=None, ge=1900, le=2100)
    source: str | None = Field(default=None, max_length=255)
    review_due_at: datetime | None = None

    @field_validator("department", "document_type", "source")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("disease_topics")
    @classmethod
    def normalize_topics(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip()
            if not item or len(item) > 50:
                raise ValueError("disease topic must be 1-50 characters")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class MetadataEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str | None = Field(default=None, max_length=40)
    snippet: str = Field(min_length=1, max_length=MAX_EVIDENCE_SNIPPET_CHARS)
    element_id: str | None = Field(default=None, max_length=80)
    page_no: int | None = Field(default=None, ge=1, le=10000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("field")
    @classmethod
    def validate_field(cls, value: str | None) -> str | None:
        if value is not None and value not in METADATA_FIELDS:
            raise ValueError("unsupported metadata field")
        return value

    @field_validator("snippet")
    @classmethod
    def normalize_snippet(cls, value: str) -> str:
        return value.strip()


class MetadataSuggestionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    fields: MetadataFields | None = None
    note: str | None = Field(default=None, max_length=500)


class MetadataSuggestionRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class MetadataSuggestionItem(BaseModel):
    id: str
    submission_id: str
    document_id: str | None
    status: str
    suggestion_source: str
    suggested_fields: MetadataFields
    confirmed_fields: MetadataFields | None = None
    evidence: list[MetadataEvidenceItem] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    parse_warnings: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    created_by: str | None = None
    reviewed_by: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None


@dataclass(frozen=True)
class MetadataSuggestionRequest:
    submission_id: str
    file_name: str
    preview_text: str | None
    parse_warnings: list[str]
    parse_quality: dict


@dataclass(frozen=True)
class MetadataSuggestionResult:
    fields: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    parse_warnings: list[str] = field(default_factory=list)
    suggestion_source: str = "disabled"
    failure_reason: str | None = None


class MetadataSuggestionPort(Protocol):
    def suggest(self, request: MetadataSuggestionRequest) -> MetadataSuggestionResult:
        ...


class DisabledMetadataSuggestionPort:
    def suggest(self, request: MetadataSuggestionRequest) -> MetadataSuggestionResult:
        del request
        return MetadataSuggestionResult(
            fields={},
            evidence=[],
            confidence={},
            parse_warnings=["metadata suggestion provider disabled"],
            suggestion_source="disabled",
        )


class FakeMetadataSuggestionPort:
    def suggest(self, request: MetadataSuggestionRequest) -> MetadataSuggestionResult:
        suffix = request.file_name.rsplit(".", 1)[-1].lower() if "." in request.file_name else None
        preview = request.preview_text or ""
        topics: list[str] = []
        if "diabetes" in preview.lower() or "糖" in preview:
            topics.append("diabetes")
        if "heart" in preview.lower() or "心" in preview:
            topics.append("cardiology")
        fields = {
            "department": "cardiology" if "cardiology" in topics else None,
            "disease_topics": topics,
            "document_type": suffix,
            "published_year": None,
            "source": "user_submission",
            "review_due_at": None,
        }
        evidence = []
        snippet = preview.strip().replace("\r", " ").replace("\n", " ")[:MAX_EVIDENCE_SNIPPET_CHARS]
        if snippet:
            evidence.append({"field": None, "snippet": snippet, "confidence": 0.3})
        return MetadataSuggestionResult(
            fields=fields,
            evidence=evidence,
            confidence={"document_type": 0.6, "source": 0.5},
            parse_warnings=[],
            suggestion_source="fake",
        )


class MetadataSuggestionService:
    def __init__(
        self,
        session: Session,
        audit: AuditPort,
        port: MetadataSuggestionPort | None = None,
    ) -> None:
        self.session = session
        self.audit = audit
        self.port = port or DisabledMetadataSuggestionPort()

    def get_or_create_for_submission(
        self,
        submission: KnowledgeSubmission,
        *,
        actor_user_id: str | None,
    ) -> MetadataSuggestion:
        return self.generate_for_submission(
            submission,
            actor_user_id=actor_user_id,
            request_id=None,
        )

    def get_existing_for_submission(
        self, submission_id: str
    ) -> MetadataSuggestion | None:
        return self.session.scalar(
            select(MetadataSuggestion).where(
                MetadataSuggestion.submission_id == submission_id
            )
        )

    def generate_for_submission(
        self,
        submission: KnowledgeSubmission,
        *,
        actor_user_id: str | None,
        request_id: str | None,
    ) -> MetadataSuggestion:
        existing = self.session.scalar(
            select(MetadataSuggestion).where(
                MetadataSuggestion.submission_id == submission.id
            )
        )
        if existing is not None:
            return existing
        request = MetadataSuggestionRequest(
            submission_id=submission.id,
            file_name=submission.original_name,
            preview_text=submission.preview_text,
            parse_warnings=list(submission.parse_warnings or []),
            parse_quality=dict(submission.parse_quality or {}),
        )
        try:
            result = self.port.suggest(request)
        except Exception as exc:
            result = MetadataSuggestionResult(
                fields={},
                evidence=[],
                confidence={},
                parse_warnings=["metadata suggestion failed"],
                suggestion_source="disabled",
                failure_reason=type(exc).__name__,
            )
        suggestion = MetadataSuggestion(
            id=str(uuid4()),
            submission_id=submission.id,
            document_id=submission.document_id,
            status="suggested",
            suggestion_source=_safe_source(result.suggestion_source),
            suggested_fields=_sanitize_fields(result.fields).model_dump(mode="json"),
            confirmed_fields=None,
            evidence=_sanitize_evidence(result.evidence),
            confidence=_sanitize_confidence(result.confidence),
            parse_warnings=_sanitize_warnings(
                [*(submission.parse_warnings or []), *result.parse_warnings]
            ),
            failure_reason=_safe_failure(result.failure_reason),
            created_by=actor_user_id,
            revision=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        try:
            self.session.add(suggestion)
            self.audit.record(
                AuditRecord(
                    actor_user_id=actor_user_id,
                    action="metadata_suggestion.generated",
                    object_type="knowledge_submission",
                    object_id=submission.id,
                    request_id=request_id,
                    details={"suggestion_source": suggestion.suggestion_source},
                )
            )
            self.session.commit()
            self.session.refresh(suggestion)
            return suggestion
        except IntegrityError:
            self.session.rollback()
            existing = self.get_existing_for_submission(submission.id)
            if existing is None:
                raise MetadataSuggestionConflictError()
            return existing
        except Exception:
            self.session.rollback()
            raise

    def generate(
        self,
        submission_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> MetadataSuggestionItem:
        submission = self.session.get(KnowledgeSubmission, submission_id)
        if submission is None:
            raise MetadataSuggestionNotFoundError()
        suggestion = self.generate_for_submission(
            submission,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        return self.to_item(suggestion)

    def accept(
        self,
        submission_id: str,
        payload: MetadataSuggestionDecisionRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> MetadataSuggestionItem:
        suggestion = self._get_existing_by_submission(submission_id)
        try:
            suggested_fields = _sanitize_fields(suggestion.suggested_fields)
            confirmed = payload.fields or suggested_fields
            status = "accepted" if confirmed == suggested_fields else "edited"
            self._transition(
                suggestion,
                status=status,
                confirmed_fields=confirmed.model_dump(mode="json"),
                actor_user_id=actor_user_id,
                expected_revision=payload.revision,
            )
            self._apply_if_published(suggestion)
            self.audit.record(
                AuditRecord(
                    actor_user_id=actor_user_id,
                    action=f"metadata_suggestion.{status}",
                    object_type="knowledge_submission",
                    object_id=submission_id,
                    request_id=request_id,
                    details={"field_count": len(_non_empty_fields(confirmed))},
                )
            )
            self.session.commit()
            self.session.refresh(suggestion)
            return self.to_item(suggestion)
        except Exception:
            self.session.rollback()
            raise

    def reject(
        self,
        submission_id: str,
        payload: MetadataSuggestionRejectRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> MetadataSuggestionItem:
        suggestion = self._get_existing_by_submission(submission_id)
        try:
            self._transition(
                suggestion,
                status="rejected",
                confirmed_fields=None,
                actor_user_id=actor_user_id,
                expected_revision=payload.revision,
            )
            self.audit.record(
                AuditRecord(
                    actor_user_id=actor_user_id,
                    action="metadata_suggestion.rejected",
                    object_type="knowledge_submission",
                    object_id=submission_id,
                    request_id=request_id,
                    details={"reason": (payload.reason or "").strip()[:120]},
                )
            )
            self.session.commit()
            self.session.refresh(suggestion)
            return self.to_item(suggestion)
        except Exception:
            self.session.rollback()
            raise

    def apply_confirmed_to_version(
        self, submission: KnowledgeSubmission, version: DocumentVersion
    ) -> None:
        suggestion = self.session.scalar(
            select(MetadataSuggestion).where(
                MetadataSuggestion.submission_id == submission.id,
                MetadataSuggestion.status.in_(["accepted", "edited"]),
            )
        )
        if suggestion is None or not suggestion.confirmed_fields:
            return
        suggestion.document_id = version.document_id
        _apply_fields_to_version(_sanitize_fields(suggestion.confirmed_fields), version)

    def _get_existing_by_submission(self, submission_id: str) -> MetadataSuggestion:
        suggestion = self.get_existing_for_submission(submission_id)
        if suggestion is None:
            raise MetadataSuggestionNotFoundError()
        return suggestion

    def _transition(
        self,
        suggestion: MetadataSuggestion,
        *,
        status: str,
        confirmed_fields: dict | None,
        actor_user_id: str,
        expected_revision: int,
    ) -> None:
        result = self.session.execute(
            update(MetadataSuggestion)
            .where(
                MetadataSuggestion.id == suggestion.id,
                MetadataSuggestion.status == "suggested",
                MetadataSuggestion.revision == expected_revision,
            )
            .values(
                status=status,
                confirmed_fields=confirmed_fields,
                reviewed_by=actor_user_id,
                reviewed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                revision=expected_revision + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise MetadataSuggestionConflictError()
        self.session.refresh(suggestion)

    def _apply_if_published(self, suggestion: MetadataSuggestion) -> None:
        submission = self.session.get(KnowledgeSubmission, suggestion.submission_id)
        if submission is None or not submission.document_id:
            return
        version = self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == submission.document_id
            )
        )
        if version is None:
            version = DocumentVersion(
                id=str(uuid4()),
                document_id=submission.document_id,
                version=1,
                source="user_submission",
                tags=[],
            )
            self.session.add(version)
            self.session.flush()
        suggestion.document_id = submission.document_id
        if suggestion.confirmed_fields:
            _apply_fields_to_version(_sanitize_fields(suggestion.confirmed_fields), version)

    @staticmethod
    def to_item(suggestion: MetadataSuggestion) -> MetadataSuggestionItem:
        return MetadataSuggestionItem(
            id=suggestion.id,
            submission_id=suggestion.submission_id,
            document_id=suggestion.document_id,
            status=suggestion.status,
            suggestion_source=suggestion.suggestion_source,
            suggested_fields=_sanitize_fields(suggestion.suggested_fields),
            confirmed_fields=(
                _sanitize_fields(suggestion.confirmed_fields)
                if suggestion.confirmed_fields
                else None
            ),
            evidence=[
                MetadataEvidenceItem.model_validate(item)
                for item in _sanitize_evidence(suggestion.evidence)
            ],
            confidence=_sanitize_confidence(suggestion.confidence),
            parse_warnings=_sanitize_warnings(suggestion.parse_warnings),
            failure_reason=suggestion.failure_reason,
            created_by=suggestion.created_by,
            reviewed_by=suggestion.reviewed_by,
            revision=suggestion.revision,
            created_at=suggestion.created_at,
            updated_at=suggestion.updated_at,
            reviewed_at=suggestion.reviewed_at,
        )


def create_metadata_suggestion_port(mode: str) -> MetadataSuggestionPort:
    if mode == "fake":
        return FakeMetadataSuggestionPort()
    if mode == "disabled":
        return DisabledMetadataSuggestionPort()
    raise MetadataSuggestionModeError()


def _sanitize_fields(fields: dict | None) -> MetadataFields:
    return MetadataFields.model_validate(fields or {})


def _sanitize_evidence(items: list[dict] | None) -> list[dict]:
    cleaned: list[dict] = []
    for item in list(items or [])[:MAX_EVIDENCE_ITEMS]:
        try:
            candidate = dict(item)
            if "snippet" in candidate:
                candidate["snippet"] = str(candidate["snippet"]).strip()[
                    :MAX_EVIDENCE_SNIPPET_CHARS
                ]
            cleaned.append(
                MetadataEvidenceItem.model_validate(candidate).model_dump(mode="json")
            )
        except Exception:
            continue
    return cleaned


def _sanitize_confidence(values: dict | None) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, value in (values or {}).items():
        if key not in METADATA_FIELDS:
            continue
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        cleaned[key] = max(0.0, min(1.0, score))
    return cleaned


def _sanitize_warnings(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for value in list(values or [])[:MAX_WARNING_ITEMS]:
        item = str(value).strip()[:MAX_WARNING_CHARS]
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _safe_source(value: str) -> str:
    cleaned = (value or "disabled").strip().lower()
    if cleaned not in ALLOWED_SUGGESTION_SOURCES:
        return "disabled"
    return cleaned


def _safe_failure(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip()[:200] or None


def _apply_fields_to_version(fields: MetadataFields, version: DocumentVersion) -> None:
    version.department = fields.department
    version.disease_topics = list(fields.disease_topics)
    version.document_type = fields.document_type
    version.published_year = fields.published_year
    version.source = fields.source
    version.review_due_at = fields.review_due_at


def _non_empty_fields(fields: MetadataFields) -> dict:
    return {
        key: value
        for key, value in fields.model_dump(mode="json").items()
        if value not in (None, [], "")
    }
