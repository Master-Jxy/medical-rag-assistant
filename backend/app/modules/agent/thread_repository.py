"""按用户隔离的Agent会话与消息持久化。"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.modules.agent.models import AgentArtifact, AgentRun, AgentStep
from app.modules.agent.thread_models import AgentMessage, AgentThread

ALLOWED_MESSAGE_METADATA_KEYS = {
    "source_ids",
    "sources",
    "artifact_ids",
    "referenced_message_ids",
    "error_code",
    "stop_reason",
}
LIST_METADATA_KEYS = {
    "source_ids",
    "artifact_ids",
    "referenced_message_ids",
}
TEXT_METADATA_KEYS = {
    "error_code",
    "stop_reason",
}
SOURCE_METADATA_KEYS = {
    "document_id",
    "chunk_id",
    "file_name",
    "page",
}
FORBIDDEN_REASONING_KEYS = {
    "reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "scratchpad",
    "private_thought",
}


class AgentThreadNotFoundError(LookupError):
    pass


class AgentMessageNotFoundError(LookupError):
    pass


class UnsafeAgentMessageMetadataError(ValueError):
    pass


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in FORBIDDEN_REASONING_KEYS
            or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


class AgentThreadRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_thread(
        self,
        *,
        user_id: str,
        title: str = "新对话",
    ) -> AgentThread:
        normalized_title = title.strip()
        if not normalized_title or len(normalized_title) > 200:
            raise ValueError("Agent会话标题长度必须为1到200个字符")
        thread = AgentThread(user_id=user_id, title=normalized_title)
        self.session.add(thread)
        self.session.flush()
        return thread

    def list_threads(
        self,
        user_id: str,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[AgentThread]:
        statement = select(AgentThread).where(AgentThread.user_id == user_id)
        if status is not None:
            statement = statement.where(AgentThread.status == status)
        return list(
            self.session.scalars(
                statement.order_by(
                    AgentThread.last_message_at.desc(),
                    AgentThread.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def get_thread(
        self,
        user_id: str,
        thread_id: str,
        *,
        include_messages: bool = False,
    ) -> AgentThread:
        statement = select(AgentThread).where(
            AgentThread.id == thread_id,
            AgentThread.user_id == user_id,
        )
        if include_messages:
            statement = statement.options(selectinload(AgentThread.messages))
        thread = self.session.scalar(statement)
        if thread is None:
            raise AgentThreadNotFoundError()
        return thread

    def reserve_turn(
        self,
        user_id: str,
        thread_id: str,
    ) -> tuple[int, int, str]:
        thread = self.session.scalar(
            select(AgentThread)
            .where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
            )
            .with_for_update()
        )
        if thread is None:
            raise AgentThreadNotFoundError()
        user_sequence = thread.next_message_sequence
        assistant_sequence = user_sequence + 1
        thread.next_message_sequence = assistant_sequence + 1
        turn_id = str(uuid4())
        self.session.flush()
        return user_sequence, assistant_sequence, turn_id

    def _reserve_message_sequence(
        self,
        user_id: str,
        thread_id: str,
    ) -> int:
        thread = self.session.scalar(
            select(AgentThread)
            .where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
            )
            .with_for_update()
        )
        if thread is None:
            raise AgentThreadNotFoundError()
        sequence_no = thread.next_message_sequence
        thread.next_message_sequence += 1
        self.session.flush()
        return sequence_no

    def rename_thread(
        self,
        user_id: str,
        thread_id: str,
        title: str,
    ) -> AgentThread:
        normalized_title = title.strip()
        if not normalized_title or len(normalized_title) > 200:
            raise ValueError("Agent会话标题长度必须为1到200个字符")
        thread = self.get_thread(user_id, thread_id)
        thread.title = normalized_title
        self.session.flush()
        return thread

    def archive_thread(
        self,
        user_id: str,
        thread_id: str,
        *,
        archived: bool = True,
    ) -> AgentThread:
        thread = self.get_thread(user_id, thread_id)
        thread.status = "archived" if archived else "active"
        self.session.flush()
        return thread

    def create_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        role: str,
        content: str,
        status: str = "completed",
        run_id: str | None = None,
        reply_to_message_id: str | None = None,
        metadata: dict[str, object] | None = None,
        sequence_no: int | None = None,
        turn_id: str | None = None,
    ) -> AgentMessage:
        thread = self.get_thread(user_id, thread_id)
        safe_metadata = dict(metadata or {})
        self._validate_metadata(safe_metadata)
        if reply_to_message_id is not None:
            self._get_message(user_id, thread_id, reply_to_message_id)
        if run_id is not None:
            run = self.session.scalar(
                select(AgentRun).where(
                    AgentRun.id == run_id,
                    AgentRun.user_id == user_id,
                    AgentRun.thread_id == thread_id,
                )
            )
            if run is None:
                raise AgentMessageNotFoundError()
        assigned_sequence = (
            sequence_no
            if sequence_no is not None
            else self._reserve_message_sequence(user_id, thread_id)
        )
        message = AgentMessage(
            thread_id=thread_id,
            user_id=user_id,
            sequence_no=assigned_sequence,
            turn_id=turn_id,
            role=role,
            content=content,
            status=status,
            run_id=run_id,
            reply_to_message_id=reply_to_message_id,
            message_metadata=safe_metadata,
        )
        self.session.add(message)
        thread.last_message_at = datetime.now(timezone.utc)
        self.session.flush()
        return message

    def list_messages(
        self,
        user_id: str,
        thread_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[AgentMessage]:
        self.get_thread(user_id, thread_id)
        rows = list(
            self.session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.thread_id == thread_id,
                    AgentMessage.user_id == user_id,
                )
                .order_by(
                    AgentMessage.sequence_no.desc(),
                )
                .offset(offset)
                .limit(limit)
            ).all()
        )
        rows.reverse()
        return rows

    def list_recent_messages(
        self,
        user_id: str,
        thread_id: str,
        *,
        before_message_id: str,
        limit: int,
    ) -> list[AgentMessage]:
        current = self._get_message(user_id, thread_id, before_message_id)
        rows = list(
            self.session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.thread_id == thread_id,
                    AgentMessage.user_id == user_id,
                    AgentMessage.sequence_no < current.sequence_no,
                    AgentMessage.status.in_(("completed", "stopped")),
                )
                .order_by(
                    AgentMessage.sequence_no.desc(),
                )
                .limit(limit)
            ).all()
        )
        rows.reverse()
        return rows

    def list_messages_for_summary(
        self,
        user_id: str,
        thread_id: str,
        *,
        keep_recent: int,
        after_message_id: str | None,
    ) -> list[AgentMessage]:
        all_messages = self.list_messages(
            user_id, thread_id, offset=0, limit=10_000
        )
        eligible = [
            item
            for item in all_messages
            if item.status in {"completed", "stopped"}
        ]
        older = eligible[:-keep_recent] if len(eligible) > keep_recent else []
        if after_message_id is None:
            return older
        ids = [item.id for item in older]
        if after_message_id not in ids:
            raise AgentMessageNotFoundError()
        return older[ids.index(after_message_id) + 1 :]

    def get_message(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
    ) -> AgentMessage:
        return self._get_message(user_id, thread_id, message_id)

    def update_message(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
        *,
        content: str,
        status: str,
        metadata: dict[str, object],
    ) -> AgentMessage:
        self._validate_metadata(metadata)
        message = self._get_message(user_id, thread_id, message_id)
        message.content = content
        message.status = status
        message.message_metadata = dict(metadata)
        self.session.flush()
        return message

    def delete_thread(self, user_id: str, thread_id: str) -> None:
        self.get_thread(user_id, thread_id)
        run_ids = list(
            self.session.scalars(
                select(AgentRun.id).where(
                    AgentRun.thread_id == thread_id,
                    AgentRun.user_id == user_id,
                )
            ).all()
        )
        if run_ids:
            self.session.execute(
                delete(AgentArtifact).where(AgentArtifact.run_id.in_(run_ids))
            )
            self.session.execute(
                delete(AgentStep).where(AgentStep.run_id.in_(run_ids))
            )
            self.session.execute(
                delete(AgentRun).where(
                    AgentRun.id.in_(run_ids),
                    AgentRun.user_id == user_id,
                )
            )
        self.session.execute(
            delete(AgentMessage).where(
                AgentMessage.thread_id == thread_id,
                AgentMessage.user_id == user_id,
            )
        )
        result = self.session.execute(
            delete(AgentThread).where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
            )
        )
        if result.rowcount != 1:
            raise AgentThreadNotFoundError()
        self.session.flush()

    def _get_message(
        self,
        user_id: str,
        thread_id: str,
        message_id: str,
    ) -> AgentMessage:
        message = self.session.scalar(
            select(AgentMessage).where(
                AgentMessage.id == message_id,
                AgentMessage.thread_id == thread_id,
                AgentMessage.user_id == user_id,
            )
        )
        if message is None:
            raise AgentMessageNotFoundError()
        return message

    @staticmethod
    def _validate_metadata(metadata: dict[str, object]) -> None:
        if set(metadata) - ALLOWED_MESSAGE_METADATA_KEYS:
            raise UnsafeAgentMessageMetadataError(
                "消息metadata包含未允许字段"
            )
        if _contains_forbidden_key(metadata):
            raise UnsafeAgentMessageMetadataError(
                "消息metadata不能包含隐藏推理字段"
            )
        if any(
            not isinstance(metadata[key], list)
            or not all(isinstance(item, str) for item in metadata[key])
            for key in LIST_METADATA_KEYS & set(metadata)
        ):
            raise UnsafeAgentMessageMetadataError(
                "消息metadata引用字段必须是字符串列表"
            )
        if any(
            metadata[key] is not None and not isinstance(metadata[key], str)
            for key in TEXT_METADATA_KEYS & set(metadata)
        ):
            raise UnsafeAgentMessageMetadataError(
                "消息metadata错误字段必须是字符串"
            )
        if "sources" in metadata:
            sources = metadata["sources"]
            if (
                not isinstance(sources, list)
                or any(
                    not isinstance(item, dict)
                    or set(item) - SOURCE_METADATA_KEYS
                    or any(
                        value is not None
                        and not isinstance(
                            value,
                            int if key == "page" else str,
                        )
                        for key, value in item.items()
                    )
                    for item in sources
                )
            ):
                raise UnsafeAgentMessageMetadataError(
                    "消息metadata来源结构不合法"
                )
