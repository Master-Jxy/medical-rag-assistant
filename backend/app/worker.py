"""Production entry point for the independent background worker container."""

import asyncio
import os
import socket

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.vector_store import VectorStoreService
from app.modules.jobs.worker import JobWorker
from app.modules.knowledge.publish_job import PublishSubmissionJobHandler


async def run() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    vector_store = VectorStoreService(settings)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    worker = JobWorker(
        session_factory,
        {
            "publish_submission": PublishSubmissionJobHandler(
                session_factory,
                settings,
                vector_store,
            )
        },
        worker_id=worker_id,
        lease_seconds=settings.job_worker_lease_seconds,
        heartbeat_seconds=settings.job_worker_heartbeat_seconds,
    )
    while True:
        result = await worker.run_once()
        if result == "idle":
            await asyncio.sleep(settings.job_worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(run())
