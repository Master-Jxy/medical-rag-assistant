"""冻结 RAG v1.1 的只读真实评估适配器。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_chroma import Chroma

from app.core.config import Settings
from app.evaluation.ports import (
    AnswerObservation,
    EvaluationQuery,
    RetrievalObservation,
    TokenUsageObservation,
)
from app.evaluation.schemas import ExpectedBehavior
from app.services.rag_service import (
    INSUFFICIENT_KNOWLEDGE_MESSAGE,
    RAG_SYSTEM_PROMPT,
    RagService,
)

FROZEN_TOP_K = 4
EVALUATION_MAX_RETRIES = 0


class ReadOnlyVectorSearch(Protocol):
    def has_documents(self) -> bool: ...

    def similarity_search(self, query: str, top_k: int) -> list[Document]: ...


class ChatInvoker(Protocol):
    def invoke(self, input: Any) -> AIMessage: ...


@dataclass
class RetrievedContextStore:
    """只存在于一次评估进程内，不连接数据库或持久化介质。"""

    _documents: dict[str, tuple[Document, ...]] = field(default_factory=dict)

    def put(self, case_id: str, documents: list[Document]) -> None:
        self._documents[case_id] = tuple(documents)

    def get(self, case_id: str) -> tuple[Document, ...]:
        try:
            return self._documents[case_id]
        except KeyError as exc:
            raise RuntimeError(f"缺少 {case_id} 的只读检索上下文") from exc


class CurrentChromaRetrievalAdapter:
    """复用当前追问补全和 similarity_search，不提供任何写方法。"""

    adapter_name = "current_chroma_read_only_v1"

    def __init__(
        self,
        vector_search: ReadOnlyVectorSearch,
        context_store: RetrievedContextStore,
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._vector_search = vector_search
        self._context_store = context_store
        self._clock = clock

    def retrieve(self, query: EvaluationQuery) -> RetrievalObservation:
        started = self._clock()
        if not self._vector_search.has_documents():
            documents: list[Document] = []
        else:
            retrieval_query = RagService._build_retrieval_query(
                query.question, list(query.history)
            )
            documents = self._vector_search.similarity_search(
                retrieval_query, FROZEN_TOP_K
            )
        self._context_store.put(query.case_id, documents)
        document_ids = tuple(self._document_id(document) for document in documents)
        return RetrievalObservation(
            source_document_ids=document_ids,
            latency_ms=(self._clock() - started) * 1000,
        )

    @staticmethod
    def _document_id(document: Document) -> str:
        document_id = str((document.metadata or {}).get("document_id") or "").strip()
        if not document_id:
            raise ValueError("Chroma 片段缺少 document_id 元数据")
        return document_id


class CurrentQwenAnswerAdapter:
    """使用冻结 Prompt 和历史消息格式调用一次 Qwen，不自动重试。"""

    adapter_name = "current_qwen_read_only_v1"

    def __init__(
        self,
        chat_model: ChatInvoker,
        context_store: RetrievedContextStore,
        *,
        input_price_per_million_cny: float,
        output_price_per_million_cny: float,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._chat_model = chat_model
        self._context_store = context_store
        self._input_price = input_price_per_million_cny
        self._output_price = output_price_per_million_cny
        self._clock = clock
        self._prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                MessagesPlaceholder("history"),
                ("human", "{question}"),
            ]
        )

    def answer(
        self, query: EvaluationQuery, source_document_ids: tuple[str, ...]
    ) -> AnswerObservation:
        started = self._clock()
        documents = list(self._context_store.get(query.case_id))
        cached_ids = tuple(
            CurrentChromaRetrievalAdapter._document_id(document)
            for document in documents
        )
        if cached_ids != source_document_ids:
            raise RuntimeError("Runner 来源 ID 与缓存检索上下文不一致")
        if not documents:
            return AnswerObservation(
                behavior=ExpectedBehavior.REFUSE,
                answer_text=INSUFFICIENT_KNOWLEDGE_MESSAGE,
                latency_ms=(self._clock() - started) * 1000,
                usage=TokenUsageObservation(0, 0, 0.0),
            )

        prompt_value = self._prompt.invoke(
            {
                "question": query.question,
                "context": RagService._build_context(documents),
                "history": RagService._to_langchain_history(list(query.history)),
            }
        )
        response = self._chat_model.invoke(prompt_value)
        answer_text = str(response.content)
        usage = self._extract_usage(response)
        behavior = (
            ExpectedBehavior.REFUSE
            if INSUFFICIENT_KNOWLEDGE_MESSAGE in answer_text
            else ExpectedBehavior.ANSWER
        )
        return AnswerObservation(
            behavior=behavior,
            answer_text=answer_text,
            latency_ms=(self._clock() - started) * 1000,
            usage=usage,
        )

    def _extract_usage(self, response: AIMessage) -> TokenUsageObservation | None:
        usage = response.usage_metadata
        if usage is not None:
            input_tokens = int(usage.get("input_tokens", 0))
            output_tokens = int(usage.get("output_tokens", 0))
        else:
            raw = response.response_metadata.get("token_usage") or response.response_metadata.get("usage")
            if not isinstance(raw, dict):
                return None
            input_tokens = int(raw.get("input_tokens", raw.get("prompt_tokens", 0)))
            output_tokens = int(raw.get("output_tokens", raw.get("completion_tokens", 0)))
        cost = (
            input_tokens * self._input_price
            + output_tokens * self._output_price
        ) / 1_000_000
        return TokenUsageObservation(input_tokens, output_tokens, cost)


class EvaluationVectorSearch:
    """评估专用 Chroma 查询对象；仅暴露检查与相似度查询。"""

    def __init__(self, store: Chroma) -> None:
        self._store = store

    def has_documents(self) -> bool:
        return bool(self._store.get(limit=1, include=[]).get("ids"))

    def similarity_search(
        self,
        query: str,
        top_k: int,
        metadata_filter: dict | None = None,
    ) -> list[Document]:
        kwargs = {"query": query, "k": top_k}
        if metadata_filter:
            kwargs["filter"] = metadata_filter
        return self._store.similarity_search(**kwargs)

    def list_documents(
        self,
        metadata_filter: dict | None = None,
    ) -> list[tuple[str, Document]]:
        kwargs = {"include": ["documents", "metadatas"]}
        if metadata_filter:
            kwargs["where"] = metadata_filter
        result = self._store.get(**kwargs)
        return [
            (
                str(chunk_id),
                Document(
                    page_content=str(content or ""),
                    metadata=dict(metadata or {}),
                ),
            )
            for chunk_id, content, metadata in zip(
                result.get("ids") or [],
                result.get("documents") or [],
                result.get("metadatas") or [],
                strict=True,
            )
            if str(content or "").strip()
        ]


def create_current_vector_search(settings: Settings) -> EvaluationVectorSearch:
    """同模型、集合与目录，唯一区别是评估调用禁止自动重试。"""
    embeddings = DashScopeEmbeddings(
        model=settings.embedding_model_name,
        dashscope_api_key=settings.require_dashscope_api_key(),
        max_retries=EVALUATION_MAX_RETRIES,
    )
    store = Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=embeddings,
        persist_directory=str(settings.chroma_persist_dir),
        create_collection_if_not_exists=False,
    )
    return EvaluationVectorSearch(store)


def create_current_chat_model(settings: Settings, *, max_output_tokens: int) -> ChatTongyi:
    """评估专用单次非流式调用，保留当前模型名并关闭 SDK 重试。"""
    return ChatTongyi(
        model=settings.chat_model_name,
        api_key=settings.require_dashscope_api_key(),
        streaming=False,
        max_retries=EVALUATION_MAX_RETRIES,
        model_kwargs={"max_tokens": max_output_tokens},
    )
