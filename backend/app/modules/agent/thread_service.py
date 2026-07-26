"""Agent会话用例与提取式滚动摘要。"""

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AgentMessageNotFoundAppError,
    AgentThreadNotFoundAppError,
)
from app.modules.agent.thread_repository import (
    AgentMessageNotFoundError,
    AgentThreadNotFoundError,
    AgentThreadRepository,
)
from app.modules.agent.thread_schemas import AgentThreadResponse


class AgentThreadService:
    def __init__(self, session: Session, *, recent_message_count: int = 8) -> None:
        self.session = session
        self.repository = AgentThreadRepository(session)
        self.recent_message_count = recent_message_count

    def create(self, user_id: str, title: str) -> AgentThreadResponse:
        thread = self.repository.create_thread(user_id=user_id, title=title)
        self.session.commit()
        return AgentThreadResponse.model_validate(thread)

    def list(
        self,
        user_id: str,
        *,
        status: str | None,
        offset: int,
        limit: int,
    ) -> list[AgentThreadResponse]:
        return [
            AgentThreadResponse.model_validate(thread)
            for thread in self.repository.list_threads(
                user_id, status=status, offset=offset, limit=limit
            )
        ]

    def get(self, user_id: str, thread_id: str) -> AgentThreadResponse:
        try:
            thread = self.repository.get_thread(user_id, thread_id)
        except AgentThreadNotFoundError as exc:
            raise AgentThreadNotFoundAppError() from exc
        return AgentThreadResponse.model_validate(thread)

    def update(
        self,
        user_id: str,
        thread_id: str,
        *,
        title: str | None,
        status: str | None,
    ) -> AgentThreadResponse:
        try:
            thread = self.repository.get_thread(user_id, thread_id)
            if title is not None:
                thread = self.repository.rename_thread(user_id, thread_id, title)
            if status is not None:
                thread = self.repository.archive_thread(
                    user_id,
                    thread_id,
                    archived=status == "archived",
                )
            self.session.commit()
        except AgentThreadNotFoundError as exc:
            self.session.rollback()
            raise AgentThreadNotFoundAppError() from exc
        return AgentThreadResponse.model_validate(thread)

    def delete(self, user_id: str, thread_id: str) -> None:
        try:
            self.repository.delete_thread(user_id, thread_id)
            self.session.commit()
        except AgentThreadNotFoundError as exc:
            self.session.rollback()
            raise AgentThreadNotFoundAppError() from exc

    def refresh_summary(self, user_id: str, thread_id: str) -> None:
        try:
            thread = self.repository.get_thread(user_id, thread_id)
            older = self.repository.list_messages_for_summary(
                user_id,
                thread_id,
                keep_recent=self.recent_message_count,
                after_message_id=thread.summary_until_message_id,
            )
        except (AgentThreadNotFoundError, AgentMessageNotFoundError) as exc:
            raise AgentMessageNotFoundAppError() from exc
        if not older:
            return
        addition = "\n".join(
            f"{'用户' if item.role == 'user' else '助手'}：{item.content[:500]}"
            for item in older
            if item.content
        )
        thread.summary = "\n".join(
            filter(None, [thread.summary or "", addition])
        )[-3000:]
        thread.summary_until_message_id = older[-1].id
        self.session.commit()
