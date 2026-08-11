"""Stage 26 leased queue and independent worker regression."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.modules.jobs.models import ProcessingJob
from app.modules.jobs.service import JobQueueService, SqlAlchemyJobService
from app.modules.jobs.worker import JobWorker


def build_factory(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def enqueue(factory, key: str, *, job_type: str = "publish_submission", max_attempts: int = 3):
    with factory() as session:
        reference = SqlAlchemyJobService(session).enqueue(
            dispatch_key=key,
            job_type=job_type,
            object_type="knowledge_submission",
            object_id=f"object-{key}",
            payload={"safe": True},
            max_attempts=max_attempts,
        )
        session.commit()
        return reference.id


def test_claim_is_exclusive_and_never_claims_human_review(tmp_path) -> None:
    engine, factory = build_factory(tmp_path)
    enqueue(factory, "human", job_type="knowledge_review")
    job_id = enqueue(factory, "publish")

    with factory() as session:
        first = JobQueueService(session).claim_next(worker_id="worker-a")
    with factory() as session:
        second = JobQueueService(session).claim_next(worker_id="worker-b")

    assert first is not None and first.id == job_id
    assert second is None
    with factory() as session:
        human = session.scalar(
            select(ProcessingJob).where(ProcessingJob.dispatch_key == "human")
        )
        assert human.status == "queued" and human.attempt_count == 0
    engine.dispose()


def test_expired_lease_is_reclaimed_and_attempt_budget_is_bounded(tmp_path) -> None:
    engine, factory = build_factory(tmp_path)
    job_id = enqueue(factory, "recover", max_attempts=2)
    with factory() as session:
        first = JobQueueService(session).claim_next(
            worker_id="worker-a", lease_seconds=30
        )
    with factory() as session:
        job = session.get(ProcessingJob, job_id)
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    with factory() as session:
        recovered = JobQueueService(session).claim_next(worker_id="worker-b")
    assert recovered is not None
    assert recovered.id == first.id
    assert recovered.attempt_count == 2
    with factory() as session:
        status = JobQueueService(session).fail(
            recovered, "BROKEN", base_backoff_seconds=0
        )
    assert status == "failed"
    engine.dispose()


def test_retry_and_cancel_keep_one_dispatch_record(tmp_path) -> None:
    engine, factory = build_factory(tmp_path)
    job_id = enqueue(factory, "retry", max_attempts=1)
    with factory() as session:
        lease = JobQueueService(session).claim_next(worker_id="worker")
    with factory() as session:
        assert JobQueueService(session).fail(lease, "FAIL") == "failed"
    with factory() as session:
        retried = JobQueueService(session).retry(job_id)
        assert retried.status == "queued"
    with factory() as session:
        cancelled = JobQueueService(session).request_cancel(job_id)
        assert cancelled.status == "cancelled"
        assert session.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))
        assert session.query(ProcessingJob).count() == 1
    engine.dispose()


def test_worker_executes_handler_and_completes_job(tmp_path) -> None:
    engine, factory = build_factory(tmp_path)
    job_id = enqueue(factory, "worker")
    seen: list[str] = []

    async def handler(lease):
        seen.append(lease.id)

    worker = JobWorker(
        factory,
        {"publish_submission": handler},
        worker_id="worker",
        lease_seconds=30,
        heartbeat_seconds=10,
    )
    assert asyncio.run(worker.run_once()) == "completed"
    assert seen == [job_id]
    with factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.status == "completed"
        assert job.progress == 100
        assert job.lease_owner is None
    engine.dispose()
