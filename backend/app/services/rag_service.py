"""普通 RAG 问答服务：检索资料、组织上下文、调用模型。"""

from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.core.exceptions import ConfigurationError, RagServiceError
from app.core.model_factory import create_chat_model
from app.infrastructure.vector_store import VectorStoreService
from app.schemas.chat import SourceItem

INSUFFICIENT_KNOWLEDGE_MESSAGE = "知识库资料不足，无法根据现有资料回答。"

RAG_SYSTEM_PROMPT = """你是医疗知识库问答助手。请严格遵守以下规则：
1. 只依据提供的知识库上下文回答，不使用上下文之外的信息补全结论。
2. 上下文不足时，明确回答“知识库资料不足，无法根据现有资料回答”。
3. 不虚构疾病结论、药物剂量、页码或资料来源。
4. 回答应简洁清楚，并提醒用户内容仅供学习和信息检索，不构成医疗建议。

知识库上下文：
{context}
"""


class RagService:
    """对外提供一次完整问答，隐藏模型与向量库的实现细节。"""

    def __init__(self) -> None:
        try:
            self.vector_store = VectorStoreService()
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", RAG_SYSTEM_PROMPT),
                    MessagesPlaceholder("history"),
                    ("human", "{question}"),
                ]
            )
            self.chain = prompt | create_chat_model() | StrOutputParser()
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

    def ask(
        self,
        question: str,
        top_k: int,
        history: list[tuple[str, str]] | None = None,
    ) -> tuple[str, list[SourceItem]]:
        """输入问题，输出模型回答和结构化引用来源。"""
        try:
            documents = self._retrieve_documents(question, top_k, history)
            if not documents:
                return INSUFFICIENT_KNOWLEDGE_MESSAGE, []

            context = self._build_context(documents)
            answer = self.chain.invoke(
                {
                    "question": question,
                    "context": context,
                    "history": self._to_langchain_history(history),
                }
            )
            sources = [self._to_source_item(document) for document in documents]
            return answer, sources
        except ConfigurationError:
            raise
        except Exception as exc:
            raise RagServiceError() from exc

    def stream_ask(
        self,
        question: str,
        top_k: int,
        history: list[tuple[str, str]] | None = None,
    ):
        """逐块生成回答，最后给出结构化引用来源。"""
        try:
            documents = self._retrieve_documents(question, top_k, history)
            if not documents:
                yield {"event": "token", "data": {"content": INSUFFICIENT_KNOWLEDGE_MESSAGE}}
                yield {"event": "sources", "data": {"sources": []}}
                return

            context = self._build_context(documents)
            for chunk in self.chain.stream(
                {
                    "question": question,
                    "context": context,
                    "history": self._to_langchain_history(history),
                }
            ):
                if chunk:
                    yield {"event": "token", "data": {"content": chunk}}

            sources = [self._to_source_item(document).model_dump() for document in documents]
            yield {"event": "sources", "data": {"sources": sources}}
        except ConfigurationError:
            raise
        except Exception as exc:
            raise RagServiceError() from exc

    def _retrieve_documents(
        self,
        question: str,
        top_k: int,
        history: list[tuple[str, str]] | None = None,
    ) -> list[Document]:
        """普通回答和流式回答共用同一套知识库检索逻辑。"""
        if not self.vector_store.has_documents():
            return []
        retrieval_query = self._build_retrieval_query(question, history)
        return self.vector_store.similarity_search(retrieval_query, top_k)

    @staticmethod
    def _build_retrieval_query(
        question: str,
        history: list[tuple[str, str]] | None,
    ) -> str:
        """用最近一个用户问题补全“它、这个”等指代，提高向量检索命中率。"""
        if history:
            for role, content in reversed(history):
                if role == "user":
                    return f"上一轮问题：{content}\n当前问题：{question}"
        return question

    @staticmethod
    def _to_langchain_history(
        history: list[tuple[str, str]] | None,
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for role, content in history or []:
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    @staticmethod
    def _build_context(documents: list[Document]) -> str:
        parts = []
        for index, document in enumerate(documents, start=1):
            source = RagService._to_source_item(document)
            location = source.file_name
            if source.page is not None:
                location += f"，第 {source.page} 页"
            parts.append(f"【资料 {index}｜{location}】\n{document.page_content}")
        return "\n\n".join(parts)

    @staticmethod
    def _to_source_item(document: Document) -> SourceItem:
        metadata = document.metadata or {}
        raw_source = str(metadata.get("source") or metadata.get("file_name") or "未知来源")
        raw_page = metadata.get("page")
        page = raw_page + 1 if isinstance(raw_page, int) else None
        return SourceItem(
            file_name=Path(raw_source).name,
            page=page,
            content=document.page_content[:500],
        )


@lru_cache
def get_rag_service() -> RagService:
    """第一次聊天请求时创建服务，之后复用模型和 Chroma 连接。"""
    return RagService()
