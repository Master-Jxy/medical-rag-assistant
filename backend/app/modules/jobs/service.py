"""任务中心查询、重试资格校验与任务生命周期维护。"""

from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.jobs.models import ProcessingJob
from app.modules.jobs.ports import JobReference
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


class SqlAlchemyJobService:
    """同一业务事务中的任务状态适配器；调用方负责 commit/rollback。"""

    def __init__(self, session: Session) -> None:
        self.session = session

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
            status="running",
            progress=initial_progress,
            attempt_count=previous_attempts + 1,
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
        job.finished_at = datetime.now(timezone.utc)
        self.session.flush()

    def fail(self, job_id: str, error_type: str) -> None:
        job = self.session.get(ProcessingJob, job_id)
        if job is None:
            raise JobNotFoundError()
        job.status = "failed"
        job.error_type = error_type
        job.finished_at = datetime.now(timezone.utc)
        self.session.flush()


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
            job.status != "failed"
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
            status=job.status,
            progress=job.progress,
            attempt_count=job.attempt_count,
            error_type=job.error_type,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
