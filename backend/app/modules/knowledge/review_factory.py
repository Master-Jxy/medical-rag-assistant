"""Knowledge review application assembly shared by HTTP and background workers."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.knowledge_parser_factory import create_knowledge_document_parser
from app.infrastructure.vector_store import VectorStoreService
from app.modules.audit.repository import SqlAlchemyAuditRecorder
from app.modules.jobs.service import SqlAlchemyJobService
from app.modules.knowledge.lifecycle import DocumentLifecycleService
from app.modules.knowledge.metadata_suggestions import (
    MetadataSuggestionService,
    create_metadata_suggestion_port,
)
from app.modules.knowledge.review_service import KnowledgeReviewService


def build_knowledge_review_service(
    session: Session,
    settings: Settings,
    vector_store: VectorStoreService,
) -> KnowledgeReviewService:
    audit = SqlAlchemyAuditRecorder(session)
    return KnowledgeReviewService(
        session,
        settings,
        DocumentLifecycleService(
            session,
            settings,
            vector_store,
            parser=create_knowledge_document_parser(settings),
        ),
        audit,
        SqlAlchemyJobService(session),
        metadata_suggestions=MetadataSuggestionService(
            session,
            audit,
            create_metadata_suggestion_port(settings.metadata_suggestion_mode),
        ),
    )
