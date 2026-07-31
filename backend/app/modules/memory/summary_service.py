from app.modules.memory.service import ConversationMemoryService


class ConversationSummaryService(ConversationMemoryService):
    """消息终态之后显式调用的摘要写入用例。"""

    def refresh_after_message(self, user_id: str, conversation_id: str) -> None:
        self._refresh_summary(user_id, conversation_id)
