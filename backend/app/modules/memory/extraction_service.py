import hashlib
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.memory.contracts import (
    MemoryCategory, MemoryExtractionModelPort, MemorySourceReaderPort,
)
from app.modules.memory.models import (
    MemoryExtractionRun, UserMemory, UserMemoryRevision, UserMemorySource,
)
from app.modules.memory.repository import MemoryRepository


class ExtractedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: MemoryCategory
    label: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    sensitive: bool
    source_message_ids: list[str] = Field(default_factory=list, max_length=50)


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[ExtractedCandidate] = Field(max_length=20)


class MemoryExtractionService:
    def __init__(
        self,
        session: Session,
        model: MemoryExtractionModelPort,
        source_reader: MemorySourceReaderPort | None = None,
        enabled: bool = True,
        usage_recorder=None,
        model_name: str | None = None,
    ):
        self.session, self.model = session, model
        self.repository = MemoryRepository(session)
        self.source_reader = source_reader
        self.enabled = enabled
        self.usage_recorder = usage_recorder
        self.model_name = model_name or getattr(model, "model_name", "unknown")

    def schedule(self, user_id: str, surface: str, thread_id: str, through_sequence: int,
                 trigger: str = "periodic") -> MemoryExtractionRun | None:
        setting = self.repository.setting(user_id)
        if not self.enabled or not setting or not setting.enabled or not setting.auto_extract_enabled:
            return None
        existing = self.repository.extraction(surface, thread_id, through_sequence)
        if existing:
            return existing
        run = MemoryExtractionRun(user_id=user_id, surface=surface, thread_id=thread_id,
                                  through_sequence=through_sequence, trigger=trigger)
        self.session.add(run)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return self.repository.extraction(surface, thread_id, through_sequence)
        return run

    def execute(
        self,
        run_id: str,
        messages: list[dict[str, str]] | None = None,
    ) -> MemoryExtractionRun:
        run = self.session.get(MemoryExtractionRun, run_id)
        if run is None:
            raise ValueError("memory extraction run not found")
        if run.status == "completed":
            return run
        if messages is None:
            if self.source_reader is None:
                raise ValueError("memory source reader is required")
            messages = self.source_reader.read_completed(
                user_id=run.user_id,
                surface=run.surface,
                thread_id=run.thread_id,
                through_sequence=run.through_sequence,
            )
        run.status, run.started_at, run.attempt_count = "running", datetime.now(timezone.utc), run.attempt_count + 1
        run.error_code = None
        self.session.commit()
        try:
            response = ExtractionResponse.model_validate(self.model.extract(messages))
            count = 0
            for candidate in response.candidates:
                if self._contains_secret(candidate.content):
                    continue
                if self.source_reader is not None and not self.source_reader.owns_messages(
                    user_id=run.user_id,
                    surface=run.surface,
                    thread_id=run.thread_id,
                    message_ids=candidate.source_message_ids,
                ):
                    continue
                normalized = " ".join(candidate.content.lower().split())
                digest = hashlib.sha256(normalized.encode()).hexdigest()
                existing = self.session.scalar(select(UserMemory).where(
                    UserMemory.user_id == run.user_id, UserMemory.normalized_hash == digest))
                if existing:
                    continue
                conflict = self.session.scalar(select(UserMemory).where(
                    UserMemory.user_id == run.user_id,
                    UserMemory.category == candidate.category.value,
                    UserMemory.label == candidate.label,
                    UserMemory.status == "active",
                ).order_by(UserMemory.updated_at.desc()))
                needs_review = candidate.sensitive or candidate.category is MemoryCategory.HEALTH_CONTEXT
                status = "candidate" if needs_review or conflict or candidate.confidence < 0.85 else "active"
                memory = UserMemory(
                    user_id=run.user_id, label=candidate.label, content=candidate.content,
                    category=candidate.category.value, status=status, source_type="extraction",
                    confidence=candidate.confidence, created_by="system", normalized_hash=digest,
                    supersedes_id=conflict.id if conflict else None,
                )
                self.session.add(memory); self.session.flush()
                self.session.add(UserMemoryRevision(
                    memory_id=memory.id, version_no=1, label=memory.label, content=memory.content,
                    category=memory.category, status=memory.status, changed_by="system",
                    change_reason="extracted",
                ))
                for message_id in dict.fromkeys(candidate.source_message_ids):
                    self.session.add(UserMemorySource(
                        memory_id=memory.id,
                        surface=run.surface,
                        thread_id=run.thread_id,
                        message_id=message_id,
                    ))
                count += 1
            run.status, run.candidate_count = "completed", count
            run.completed_at = datetime.now(timezone.utc)
        except (ValidationError, ValueError, TypeError):
            self.session.rollback()
            run = self.session.get(MemoryExtractionRun, run_id)
            run.status, run.error_code, run.completed_at = "failed", "INVALID_MODEL_RESPONSE", datetime.now(timezone.utc)
        except Exception:
            self.session.rollback()
            run = self.session.get(MemoryExtractionRun, run_id)
            run.status, run.error_code, run.completed_at = "failed", "MODEL_CALL_FAILED", datetime.now(timezone.utc)
        self.session.commit()
        self._record_usage(run)
        return run

    def recover_pending(self, *, limit: int = 10) -> list[MemoryExtractionRun]:
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=15)
        rows = self.session.scalars(
            select(MemoryExtractionRun).where(
                MemoryExtractionRun.attempt_count < 2,
                (
                    MemoryExtractionRun.status.in_(("pending", "failed"))
                    | (
                        (MemoryExtractionRun.status == "running")
                        & (MemoryExtractionRun.started_at < stale_before)
                    )
                ),
            ).order_by(MemoryExtractionRun.created_at).limit(limit)
        ).all()
        return [self.execute(row.id) for row in rows]

    def _record_usage(self, run: MemoryExtractionRun) -> None:
        if self.usage_recorder is None:
            return
        drain = getattr(self.model, "drain_usage", None)
        usage = drain() if callable(drain) else None
        if usage is None:
            return
        try:
            self.usage_recorder.record(
                call_id=f"memory:{run.id}:extract",
                request_id=None,
                user_id=run.user_id,
                surface="memory",
                operation="extract",
                model_name=self.model_name,
                usage=usage,
                usage_group_id=run.id,
                status="completed" if run.status == "completed" else "failed",
                quota_billable=False,
            )
        except Exception:
            self.session.rollback()

    @staticmethod
    def _contains_secret(text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in ("password", "api key", "apikey", "验证码", "授权码", "私钥", "token"))
