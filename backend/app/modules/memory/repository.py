from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.memory.models import MemoryExtractionRun, UserMemory, UserMemorySetting


class MemoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def setting(self, user_id: str) -> UserMemorySetting | None:
        return self.session.get(UserMemorySetting, user_id)

    def owned(self, user_id: str, memory_id: str) -> UserMemory | None:
        return self.session.scalar(select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == user_id))

    def active(self, user_id: str) -> list[UserMemory]:
        now = datetime.now(timezone.utc)
        return list(self.session.scalars(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                (UserMemory.valid_until.is_(None) | (UserMemory.valid_until > now)),
            )
        ).all())

    def extraction(self, surface: str, thread_id: str, through_sequence: int) -> MemoryExtractionRun | None:
        return self.session.scalar(select(MemoryExtractionRun).where(
            MemoryExtractionRun.surface == surface,
            MemoryExtractionRun.thread_id == thread_id,
            MemoryExtractionRun.through_sequence == through_sequence,
        ))
