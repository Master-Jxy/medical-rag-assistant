"""Background handler that reuses the public knowledge review application service."""

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.infrastructure.vector_store import VectorStoreService
from app.modules.jobs.ports import JobLease
from app.modules.knowledge.review_factory import build_knowledge_review_service


class PublishSubmissionJobHandler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        vector_store: VectorStoreService,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.vector_store = vector_store

    async def __call__(self, lease: JobLease) -> None:
        if lease.object_type != "knowledge_submission":
            raise ValueError("INVALID_JOB_OBJECT")
        with self.session_factory() as session:
            service = build_knowledge_review_service(
                session,
                self.settings,
                self.vector_store,
            )
            await service.execute_queued_publish(
                job_id=lease.id,
                submission_id=lease.object_id,
                payload=lease.payload,
            )
