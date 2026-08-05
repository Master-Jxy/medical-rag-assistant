"""知识有效期和复核任务扫描。"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.jobs.ports import JobPort
from app.modules.knowledge.models import DocumentVersion, KnowledgeDocument


class KnowledgeGovernanceService:
    def __init__(self, session: Session, jobs: JobPort):
        self.session = session
        self.jobs = jobs

    def scan_due_reviews(self, now: datetime) -> list[str]:
        versions = self.session.scalars(
            select(DocumentVersion)
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentVersion.document_id)
            .where(
                KnowledgeDocument.status.in_(("published", "ready")),
                DocumentVersion.review_due_at.is_not(None),
                DocumentVersion.review_due_at <= now,
                DocumentVersion.review_status.in_(("current", "due")),
                or_(
                    DocumentVersion.expires_at.is_(None),
                    DocumentVersion.expires_at > now,
                ),
            )
            .with_for_update()
        ).all()
        job_ids = []
        for version in versions:
            version.review_status = "in_review"
            job = self.jobs.start(
                job_type="knowledge_review",
                object_type="knowledge_document",
                object_id=version.document_id,
                initial_progress=0,
            )
            job_ids.append(job.id)
        self.session.commit()
        return job_ids
