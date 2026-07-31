"""用独立Session恢复持久化记忆提取任务。"""

import logging

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.memory_extraction_model import DashScopeMemoryExtractionModel
from app.infrastructure.memory_source_reader import SqlAlchemyMemorySourceReader
from app.modules.memory.contracts import DisabledMemoryExtractionModel
from app.modules.memory.extraction_service import MemoryExtractionService
from app.modules.usage.service import ModelUsageRecorder

logger = logging.getLogger(__name__)


def run_memory_extraction_recovery(limit: int = 10) -> None:
    settings = get_settings()
    if not settings.memory_auto_extraction_enabled:
        return
    with get_session_factory()() as session:
        model = DashScopeMemoryExtractionModel(settings)
        service = MemoryExtractionService(
            session,
            model,
            SqlAlchemyMemorySourceReader(session),
            enabled=True,
            usage_recorder=ModelUsageRecorder(session),
        )
        try:
            service.recover_pending(limit=limit)
        except Exception as exc:
            session.rollback()
            logger.warning("memory_extraction_recovery_failed error_type=%s", type(exc).__name__)


def build_memory_scheduler(session):
    settings = get_settings()
    return MemoryExtractionService(
        session,
        DisabledMemoryExtractionModel(),
        SqlAlchemyMemorySourceReader(session),
        enabled=settings.memory_auto_extraction_enabled,
    )
