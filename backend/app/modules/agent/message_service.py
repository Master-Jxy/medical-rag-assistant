"""Agent消息读取和稳定状态更新用例。"""

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
from app.modules.agent.thread_schemas import AgentMessageResponse
from app.modules.usage.query_service import UsageQueryService


class AgentMessageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AgentThreadRepository(session)
        self.usage = UsageQueryService(session)

    def _response(self, message) -> AgentMessageResponse:
        response = AgentMessageResponse.model_validate(message)
        if message.role == "assistant":
            return response.model_copy(update={
                "usage": self.usage.group_summary(message.id, message.user_id)
            })
        return response

    def list(
        self,
        user_id: str,
        thread_id: str,
        *,
        offset: int,
        limit: int,
    ) -> list[AgentMessageResponse]:
        try:
            messages = self.repository.list_messages(
                user_id, thread_id, offset=offset, limit=limit
            )
        except AgentThreadNotFoundError as exc:
            raise AgentThreadNotFoundAppError() from exc
        return [
            self._response(message) for message in messages
        ]

    def get(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
    ) -> AgentMessageResponse:
        try:
            message = self.repository.get_message(
                user_id, thread_id, message_id
            )
        except AgentMessageNotFoundError as exc:
            raise AgentMessageNotFoundAppError() from exc
        return self._response(message)
