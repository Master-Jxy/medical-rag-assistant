"""Bounded single-process worker for leased MySQL jobs."""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session, sessionmaker

from app.modules.jobs.ports import JobLease
from app.modules.jobs.service import JobLeaseLostError, JobQueueService

JobHandler = Callable[[JobLease], Awaitable[None]]


class JobWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        handlers: dict[str, JobHandler],
        *,
        worker_id: str,
        lease_seconds: int = 60,
        heartbeat_seconds: int = 15,
    ) -> None:
        self.session_factory = session_factory
        self.handlers = dict(handlers)
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

    async def run_once(self) -> str:
        with self.session_factory() as session:
            lease = JobQueueService(session).claim_next(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                allowed_job_types=tuple(self.handlers),
            )
        if lease is None:
            return "idle"
        handler = self.handlers.get(lease.job_type)
        if handler is None:
            with self.session_factory() as session:
                JobQueueService(session).fail(lease, "UNSUPPORTED_JOB_TYPE")
            return "failed"

        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(lease, stop_heartbeat)
        )
        try:
            await handler(lease)
            with self.session_factory() as session:
                queue = JobQueueService(session)
                if queue.cancellation_requested(lease):
                    queue.fail(lease, "CANCELLED")
                    return "cancelled"
                queue.complete(lease)
            return "completed"
        except JobLeaseLostError:
            return "lease_lost"
        except Exception as exc:
            error_code = type(exc).__name__[:100]
            with self.session_factory() as session:
                try:
                    return JobQueueService(session).fail(lease, error_code)
                except JobLeaseLostError:
                    return "lease_lost"
        finally:
            stop_heartbeat.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

    async def _heartbeat_loop(self, lease: JobLease, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_seconds)
                return
            except TimeoutError:
                pass
            with self.session_factory() as session:
                JobQueueService(session).heartbeat(
                    lease,
                    lease_seconds=self.lease_seconds,
                )
