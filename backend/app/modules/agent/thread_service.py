"""Agent会话用例与提取式滚动摘要。"""

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AgentMessageNotFoundAppError,
    AgentRunConflictError,
    AgentThreadNotFoundAppError,
)
from app.modules.agent.thread_repository import (
    AgentMessageNotFoundError,
    AgentThreadNotFoundError,
    AgentThreadRepository,
    AgentThreadRuntimeRecord,
)
from app.modules.agent.thread_schemas import (
    AgentThreadReadResponse,
    AgentThreadResponse,
)


class AgentThreadService:
    def __init__(self, session: Session, *, recent_message_count: int = 8) -> None:
        self.session = session
        self.repository = AgentThreadRepository(session)
        self.recent_message_count = recent_message_count

    def create(
        self,
        user_id: str,
        title: str,
        assistant_mode: str = "general",
    ) -> AgentThreadResponse:
        thread = self.repository.create_thread(
            user_id=user_id,
            title=title,
            assistant_mode=assistant_mode,
        )
        self.session.commit()
        return self._to_response(
            self.repository.get_thread_summary(user_id, thread.id)
        )

    def list(
        self,
        user_id: str,
        *,
        status: str | None,
        offset: int,
        limit: int,
    ) -> list[AgentThreadResponse]:
        return [
            self._to_response(record)
            for record in self.repository.list_thread_summaries(
                user_id, status=status, offset=offset, limit=limit
            )
        ]

    def get(self, user_id: str, thread_id: str) -> AgentThreadResponse:
        try:
            record = self.repository.get_thread_summary(user_id, thread_id)
        except AgentThreadNotFoundError as exc:
            raise AgentThreadNotFoundAppError() from exc
        return self._to_response(record)

    def update(
        self,
        user_id: str,
        thread_id: str,
        *,
        title: str | None,
        status: str | None,
        assistant_mode: str | None = None,
    ) -> AgentThreadResponse:
        try:
            requires_idle = status is not None or assistant_mode is not None
            thread = self.repository.get_thread(
                user_id,
                thread_id,
                for_update=requires_idle,
            )
            if requires_idle:
                runtime = self.repository.get_thread_summary(user_id, thread_id)
                if runtime.active_run_id:
                    self.session.rollback()
                    raise AgentRunConflictError()
            if title is not None:
                thread = self.repository.rename_thread(user_id, thread_id, title)
            if status is not None:
                thread = self.repository.archive_thread(
                    user_id,
                    thread_id,
                    archived=status == "archived",
                )
            if assistant_mode is not None:
                thread = self.repository.change_assistant_mode(
                    user_id,
                    thread_id,
                    assistant_mode,
                )
            self.session.commit()
        except AgentThreadNotFoundError as exc:
            self.session.rollback()
            raise AgentThreadNotFoundAppError() from exc
        return self._to_response(
            self.repository.get_thread_summary(user_id, thread.id)
        )

    def mark_read(
        self,
        user_id: str,
        thread_id: str,
        last_read_sequence: int,
    ) -> AgentThreadReadResponse:
        try:
            marker = self.repository.mark_read(
                user_id,
                thread_id,
                last_read_sequence,
            )
            self.session.commit()
        except AgentThreadNotFoundError as exc:
            self.session.rollback()
            raise AgentThreadNotFoundAppError() from exc
        return AgentThreadReadResponse(
            thread_id=thread_id,
            last_read_sequence=marker,
        )

    def delete(self, user_id: str, thread_id: str) -> None:
        try:
            self.repository.get_thread(user_id, thread_id, for_update=True)
            runtime = self.repository.get_thread_summary(user_id, thread_id)
            if runtime.active_run_id:
                self.session.rollback()
                raise AgentRunConflictError()
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

    @staticmethod
    def _to_response(record: AgentThreadRuntimeRecord) -> AgentThreadResponse:
        payload = AgentThreadResponse.model_validate(record.thread).model_dump()
        payload.update(
            run_status=record.run_status,
            active_run_id=record.active_run_id,
            has_unread=record.has_unread,
            last_message_status=record.last_message_status,
        )
        return AgentThreadResponse.model_validate(payload)
