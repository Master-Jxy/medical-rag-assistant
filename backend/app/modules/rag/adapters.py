"""对当前查询规则、Chroma 与通义千问实现的薄适配器。"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.core.model_factory import create_chat_model
from app.infrastructure.async_chat_model import DashScopeAsyncChatModel
from app.infrastructure.vector_store import VectorStoreService
from app.modules.rag.ports import (
    ChatHistory,
    KnowledgeSearchOptions,
    RetrievedChunk,
)

RAG_SYSTEM_PROMPT = """你是医疗知识库问答助手。请严格遵守以下规则：
1. 只依据提供的知识库上下文回答，不使用上下文之外的信息补全结论。
2. 上下文不足时，明确回答“知识库资料不足，无法根据现有资料回答”。
3. 不虚构疾病结论、药物剂量、页码或资料来源。
4. 回答应简洁清楚，并提醒用户内容仅供学习和信息检索，不构成医疗建议。

知识库上下文：
{context}
"""


class CurrentQueryBuilderAdapter:
    """保持现有“最近用户问题 + 当前问题”的指代补全规则。"""

    def build(self, question: str, history: ChatHistory | None) -> str:
        if history:
            for role, content in reversed(history):
                if role == "user":
                    return f"上一轮问题：{content}\n当前问题：{question}"
        return question


class CurrentChromaKnowledgeSearchAdapter:
    """把现有 Chroma/LangChain Document 转为模块内统一片段。"""

    def __init__(self, vector_store: VectorStoreService | None = None) -> None:
        self.vector_store = vector_store or VectorStoreService()

    def search(
        self,
        query: str,
        top_k: int,
        options: KnowledgeSearchOptions | None = None,
    ) -> list[RetrievedChunk]:
        if not self.vector_store.has_documents():
            return []
        active_options = options or KnowledgeSearchOptions()
        chroma_filter = self._to_chroma_filter(active_options)
        if active_options.minimum_relevance_score is None:
            documents = (
                self.vector_store.similarity_search(query, top_k, chroma_filter)
                if chroma_filter
                else self.vector_store.similarity_search(query, top_k)
            )
            documents_with_scores = [
                (document, None)
                for document in documents
            ]
        else:
            scored_documents = (
                self.vector_store.similarity_search_with_relevance_scores(
                    query, top_k, chroma_filter
                )
                if chroma_filter
                else self.vector_store.similarity_search_with_relevance_scores(
                    query, top_k
                )
            )
            documents_with_scores = [
                (document, score)
                for document, score in scored_documents
                if score >= active_options.minimum_relevance_score
            ]
        chunks: list[RetrievedChunk] = []
        for document, score in documents_with_scores:
            metadata = document.metadata or {}
            raw_source = str(
                metadata.get("source") or metadata.get("file_name") or "未知来源"
            )
            raw_page = metadata.get("page")
            chunks.append(
                RetrievedChunk(
                    content=document.page_content,
                    file_name=Path(raw_source).name,
                    page=raw_page + 1 if isinstance(raw_page, int) else None,
                    chunk_id=(
                        str(metadata["chunk_id"])
                        if metadata.get("chunk_id") is not None
                        else None
                    ),
                    document_id=(
                        str(metadata["document_id"])
                        if metadata.get("document_id") is not None
                        else None
                    ),
                    relevance_score=score,
                    metadata=dict(metadata),
                )
            )
        return chunks

    @staticmethod
    def _to_chroma_filter(options: KnowledgeSearchOptions) -> dict | None:
        items = options.metadata_filter.as_items()
        if not items:
            return None
        conditions = [{key: {"$eq": value}} for key, value in items]
        return conditions[0] if len(conditions) == 1 else {"$and": conditions}


class CurrentQwenAnswerGeneratorAdapter:
    """保持现有 Prompt、LangChain普通流与可取消DashScope异步流。"""

    def __init__(self) -> None:
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                MessagesPlaceholder("history"),
                ("human", "{question}"),
            ]
        )
        self.chain = self.prompt | create_chat_model() | StrOutputParser()
        self.async_chat_model = DashScopeAsyncChatModel()

    def answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> str:
        return self.chain.invoke(self._inputs(question, history, chunks))

    def stream_answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> Iterator[str]:
        yield from self.chain.stream(self._inputs(question, history, chunks))

    async def astream_answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> AsyncIterator[str]:
        prompt_value = self.prompt.invoke(self._inputs(question, history, chunks))
        messages = to_dashscope_messages(prompt_value.to_messages())
        async for chunk in self.async_chat_model.stream(messages):
            yield chunk

    @staticmethod
    def _inputs(
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> dict[str, object]:
        return {
            "question": question,
            "context": build_context(chunks),
            "history": to_langchain_history(history),
        }


def to_langchain_history(history: ChatHistory | None) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for role, content in history or []:
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def to_dashscope_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            role = "system"
        elif isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        else:
            raise TypeError(f"不支持的模型消息类型：{type(message).__name__}")
        converted.append({"role": role, "content": str(message.content)})
    return converted


def build_context(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for index, chunk in enumerate(chunks, start=1):
        location = chunk.file_name
        if chunk.page is not None:
            location += f"，第 {chunk.page} 页"
        parts.append(f"【资料 {index}｜{location}】\n{chunk.content}")
    return "\n\n".join(parts)
