"""任务中心查询与单机 MySQL 租约队列。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.jobs.models import ProcessingJob
from app.modules.jobs.ports import JobLease, JobReference
from app.modules.jobs.schemas import JobItem, JobListResponse


class JobNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("未找到处理任务", code="JOB_NOT_FOUND", status_code=404)


class JobNotRetryableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "当前任务不能重试",
            code="JOB_NOT_RETRYABLE",
            status_code=409,
        )


class JobLeaseLostError(RuntimeError):
    pass


class JobNotCancellableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "当前任务不能取消",
            code="JOB_NOT_CANCELLABLE",
            status_code=409,
        )


class SqlAlchemyJobService:
    """同一业务事务中的任务状态适配器；调用方负责 commit/rollback。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        *,
        dispatch_key: str,
        job_type: str,
        object_type: str,
        object_id: str,
        payload: dict | None = None,
        max_attempts: int = 3,
    ) -> JobReference:
        existing = self.session.scalar(
            select(ProcessingJob).where(ProcessingJob.dispatch_key == dispatch_key)
        )
        if existing is not None:
            return JobReference(id=existing.id, attempt_count=existing.attempt_count)
        job = ProcessingJob(
            job_type=job_type,
            object_type=object_type,
            object_id=object_id,
            dispatch_key=dispatch_key,
            payload=dict(payload or {}),
            status="queued",
            progress=0,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=datetime.now(timezone.utc),
        )
        self.session.add(job)
        self.session.flush()
        return JobReference(id=job.id, attempt_count=0)

    def start(
        self,
        *,
        job_type: str,
        object_type: str,
        object_id: str,
        initial_progress: int,
    ) -> JobReference:
        previous_attempts = self.session.scalar(
            select(func.max(ProcessingJob.attempt_count)).where(
                ProcessingJob.object_type == object_type,
                ProcessingJob.object_id == object_id,
                ProcessingJob.job_type == job_type,
            )
        ) or 0
        job = ProcessingJob(
            job_type=job_type,
            object_type=object_type,
            object_id=object_id,
            dispatch_key=f"direct:{uuid4()}",
            payload={},
            status="running",
            progress=initial_progress,
            attempt_count=previous_attempts + 1,
            max_attempts=1,
            available_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(job)
        self.session.flush()
        return JobReference(id=job.id, attempt_count=job.attempt_count)

    def complete(self, job_id: str) -> None:
        job = self.session.get(ProcessingJob, job_id)
        if job is None:
            raise JobNotFoundError()
        job.status = "completed"
        job.progress = 100
        job.error_type = None
        job.last_error_code = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.finished_at = datetime.now(timezone.utc)
        self.session.flush()

    def fail(self, job_id: str, error_type: str) -> None:
        job = self.session.get(ProcessingJob, job_id)
        if job is None:
            raise JobNotFoundError()
        job.status = "failed"
        job.error_type = error_type
        job.last_error_code = error_type
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.finished_at = datetime.now(timezone.utc)
        self.session.flush()

    def complete_running_for_object(
        self,
        *,
        job_type: str,
        object_type: str,
        object_id: str,
    ) -> int:
        jobs = self.session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.job_type == job_type,
                ProcessingJob.object_type == object_type,
                ProcessingJob.object_id == object_id,
                ProcessingJob.status == "running",
            )
        ).all()
        for job in jobs:
            self.complete(job.id)
        return len(jobs)


class JobQueueService:
    """Worker 使用的短事务租约队列；业务处理在租约事务之外执行。"""

    DEFAULT_JOB_TYPES = ("publish_submission", "document_enrichment", "maintenance_cleanup")

    def __init__(self, session: Session) -> None:
        self.session = session

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        allowed_job_types: tuple[str, ...] | None = None,
    ) -> JobLease | None:
        now = datetime.now(timezone.utc)
        self._recover_expired(now)
        job_types = allowed_job_types or self.DEFAULT_JOB_TYPES
        statement = (
            select(ProcessingJob)
            .where(
                ProcessingJob.job_type.in_(job_types),
                ProcessingJob.status.in_(("queued", "retry_wait")),
                ProcessingJob.available_at <= now,
                ProcessingJob.cancel_requested_at.is_(None),
            )
            .order_by(ProcessingJob.available_at.asc(), ProcessingJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = self.session.scalar(statement)
        if job is None:
            self.session.commit()
            return None
        job.status = "running"
        job.attempt_count += 1
        job.progress = max(job.progress, 1)
        job.started_at = now
        job.finished_at = None
        job.error_type = None
        job.last_error_code = None
        job.lease_owner = worker_id
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.session.commit()
        return JobLease(
            id=job.id,
            job_type=job.job_type,
            object_type=job.object_type,
            object_id=job.object_id,
            payload=dict(job.payload or {}),
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            lease_owner=worker_id,
        )

    def heartbeat(self, lease: JobLease, *, lease_seconds: int = 60, progress: int | None = None) -> None:
        now = datetime.now(timezone.utc)
        values: dict[str, object] = {
            "heartbeat_at": now,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
        }
        if progress is not None:
            values["progress"] = max(0, min(99, progress))
        result = self.session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == lease.id,
                ProcessingJob.status == "running",
                ProcessingJob.lease_owner == lease.lease_owner,
                ProcessingJob.cancel_requested_at.is_(None),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise JobLeaseLostError(lease.id)
        self.session.commit()

    def complete(self, lease: JobLease) -> None:
        now = datetime.now(timezone.utc)
        job = self.session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == lease.id,
                ProcessingJob.status == "running",
                ProcessingJob.lease_owner == lease.lease_owner,
            )
            .with_for_update()
        )
        if job is None:
            self.session.rollback()
            raise JobLeaseLostError(lease.id)
        job.status = "cancelled" if job.cancel_requested_at else "completed"
        job.progress = job.progress if job.cancel_requested_at else 100
        job.error_type = "CANCELLED" if job.cancel_requested_at else None
        job.last_error_code = "CANCELLED" if job.cancel_requested_at else None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.finished_at = now
        self.session.commit()

    def fail(
        self,
        lease: JobLease,
        error_code: str,
        *,
        base_backoff_seconds: int = 5,
        max_backoff_seconds: int = 300,
    ) -> str:
        job = self.session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == lease.id,
                ProcessingJob.status == "running",
                ProcessingJob.lease_owner == lease.lease_owner,
            )
            .with_for_update()
        )
        if job is None:
            self.session.rollback()
            raise JobLeaseLostError(lease.id)
        now = datetime.now(timezone.utc)
        job.error_type = error_code[:100]
        job.last_error_code = error_code[:100]
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.finished_at = now
        elif job.attempt_count < job.max_attempts:
            delay = min(max_backoff_seconds, base_backoff_seconds * (2 ** max(0, job.attempt_count - 1)))
            job.status = "retry_wait"
            job.available_at = now + timedelta(seconds=delay)
            job.finished_at = None
        else:
            job.status = "failed"
            job.finished_at = now
        self.session.commit()
        return job.status

    def cancellation_requested(self, lease: JobLease) -> bool:
        return bool(
            self.session.scalar(
                select(ProcessingJob.cancel_requested_at).where(
                    ProcessingJob.id == lease.id,
                    ProcessingJob.lease_owner == lease.lease_owner,
                )
            )
        )

    def _recover_expired(self, now: datetime) -> int:
        jobs = self.session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "running",
                ProcessingJob.lease_expires_at.is_not(None),
                ProcessingJob.lease_expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.last_error_code = "LEASE_EXPIRED"
            if job.cancel_requested_at is not None:
                job.status = "cancelled"
                job.finished_at = now
            elif job.attempt_count >= job.max_attempts:
                job.status = "failed"
                job.error_type = "LEASE_EXPIRED"
                job.finished_at = now
            else:
                job.status = "queued"
                job.available_at = now
                job.finished_at = None
        return len(jobs)

    def request_cancel(self, job_id: str) -> ProcessingJob:
        job = self.session.scalar(
            select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        )
        if job is None:
            raise JobNotFoundError()
        if job.status in {"completed", "failed", "cancelled"}:
            raise JobNotCancellableError()
        now = datetime.now(timezone.utc)
        job.cancel_requested_at = now
        if job.status in {"queued", "retry_wait"}:
            job.status = "cancelled"
            job.finished_at = now
        self.session.commit()
        return job

    def retry(self, job_id: str) -> ProcessingJob:
        job = self.session.scalar(
            select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        )
        if job is None:
            raise JobNotFoundError()
        if job.status not in {"failed", "cancelled"}:
            raise JobNotRetryableError()
        job.status = "queued"
        job.progress = 0
        job.available_at = datetime.now(timezone.utc)
        job.finished_at = None
        job.error_type = None
        job.last_error_code = None
        job.cancel_requested_at = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        self.session.commit()
        return job


class JobQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_jobs(
        self, *, status: str | None, offset: int, limit: int
    ) -> JobListResponse:
        statement = select(ProcessingJob)
        count_statement = select(func.count()).select_from(ProcessingJob)
        if status:
            statement = statement.where(ProcessingJob.status == status)
            count_statement = count_statement.where(ProcessingJob.status == status)
        jobs = self.session.scalars(
            statement.order_by(
                ProcessingJob.created_at.desc(), ProcessingJob.id.desc()
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return JobListResponse(
            items=[self.to_item(job) for job in jobs],
            total=self.session.scalar(count_statement) or 0,
            offset=offset,
            limit=limit,
        )

    def require_retryable_publish_job(self, job_id: str) -> ProcessingJob:
        job = self.session.get(ProcessingJob, job_id)
        if job is None:
            raise JobNotFoundError()
        if (
            job.status not in {"failed", "cancelled"}
            or job.job_type != "publish_submission"
            or job.object_type != "knowledge_submission"
        ):
            raise JobNotRetryableError()
        return job

    @staticmethod
    def to_item(job: ProcessingJob) -> JobItem:
        return JobItem(
            job_id=job.id,
            job_type=job.job_type,
            object_type=job.object_type,
            object_id=job.object_id,
            dispatch_key=job.dispatch_key,
            status=job.status,
            progress=job.progress,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            error_type=job.error_type,
            last_error_code=job.last_error_code,
            available_at=job.available_at,
            lease_owner=job.lease_owner,
            lease_expires_at=job.lease_expires_at,
            heartbeat_at=job.heartbeat_at,
            cancel_requested_at=job.cancel_requested_at,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
