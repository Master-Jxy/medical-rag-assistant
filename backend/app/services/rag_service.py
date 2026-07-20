"""普通 RAG 应用服务：编排查询构造、知识检索和回答生成。"""

from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage

from app.core.exceptions import ConfigurationError, RagServiceError
from app.core.config import get_settings
from app.modules.rag.adapters import (
    RAG_SYSTEM_PROMPT,
    CurrentQueryBuilderAdapter,
    CurrentQwenAnswerGeneratorAdapter,
    to_dashscope_messages,
    to_langchain_history,
)
from app.modules.rag.ports import (
    AnswerGeneratorPort,
    ChatHistory,
    KnowledgeSearchPort,
    QueryBuilderPort,
    RetrievedChunk,
)
from app.modules.rag.policies import (
    DEFAULT_INSUFFICIENT_KNOWLEDGE_MESSAGE,
    RagRetrievalPolicy,
)
from app.modules.rag.hybrid_search import create_current_knowledge_search
from app.modules.rag.rerank import RerankStage, create_current_rerank_stage
from app.schemas.chat import SourceItem

INSUFFICIENT_KNOWLEDGE_MESSAGE = DEFAULT_INSUFFICIENT_KNOWLEDGE_MESSAGE


class RagService:
    """统一问答入口；三个内部能力均可通过稳定 Port 独立替换。"""

    def __init__(
        self,
        query_builder: QueryBuilderPort | None = None,
        knowledge_search: KnowledgeSearchPort | None = None,
        answer_generator: AnswerGeneratorPort | None = None,
        retrieval_policy: RagRetrievalPolicy | None = None,
        rerank_stage: RerankStage | None = None,
    ) -> None:
        try:
            settings = get_settings()
            self.query_builder = query_builder or CurrentQueryBuilderAdapter()
            self.knowledge_search = (
                knowledge_search or create_current_knowledge_search(settings)
            )
            self.answer_generator = (
                answer_generator or CurrentQwenAnswerGeneratorAdapter()
            )
            self.retrieval_policy = retrieval_policy or RagRetrievalPolicy.from_settings(
                settings
            )
            self.rerank_stage = rerank_stage or create_current_rerank_stage(settings)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

    def ask(
        self,
        question: str,
        top_k: int,
        history: ChatHistory | None = None,
    ) -> tuple[str, list[SourceItem]]:
        """输入问题，输出模型回答和结构化引用来源。"""
        try:
            chunks = self._retrieve_chunks(question, top_k, history)
            if not chunks:
                return self.retrieval_policy.insufficient_knowledge_message, []
            answer = self.answer_generator.answer(question, history, chunks)
            return answer, [self._chunk_to_source_item(chunk) for chunk in chunks]
        except ConfigurationError:
            raise
        except Exception as exc:
            raise RagServiceError() from exc

    def stream_ask(
        self,
        question: str,
        top_k: int,
        history: ChatHistory | None = None,
    ):
        """逐块生成回答，最后给出结构化引用来源。"""
        try:
            chunks = self._retrieve_chunks(question, top_k, history)
            if not chunks:
                yield {
                    "event": "token",
                    "data": {
                        "content": self.retrieval_policy.insufficient_knowledge_message
                    },
                }
                yield {"event": "sources", "data": {"sources": []}}
                return

            for chunk in self.answer_generator.stream_answer(question, history, chunks):
                if chunk:
                    yield {"event": "token", "data": {"content": chunk}}
            yield {
                "event": "sources",
                "data": {
                    "sources": [
                        self._chunk_to_source_item(chunk).model_dump()
                        for chunk in chunks
                    ]
                },
            }
        except ConfigurationError:
            raise
        except Exception as exc:
            raise RagServiceError() from exc

    async def astream_ask(
        self,
        question: str,
        top_k: int,
        history: ChatHistory | None = None,
    ):
        """使用可取消的异步 HTTP 流生成回答。"""
        try:
            chunks = self._retrieve_chunks(question, top_k, history)
            if not chunks:
                yield {
                    "event": "token",
                    "data": {
                        "content": self.retrieval_policy.insufficient_knowledge_message
                    },
                }
                yield {"event": "sources", "data": {"sources": []}}
                return

            async for chunk in self.answer_generator.astream_answer(
                question, history, chunks
            ):
                yield {"event": "token", "data": {"content": chunk}}
            yield {
                "event": "sources",
                "data": {
                    "sources": [
                        self._chunk_to_source_item(chunk).model_dump()
                        for chunk in chunks
                    ]
                },
            }
        except ConfigurationError:
            raise
        except Exception as exc:
            raise RagServiceError() from exc

    def _retrieve_chunks(
        self,
        question: str,
        top_k: int,
        history: ChatHistory | None,
    ) -> list[RetrievedChunk]:
        query = self.query_builder.build(question, history)
        options = self.retrieval_policy.search_options
        if options.is_disabled:
            chunks = self.knowledge_search.search(query, top_k)
        else:
            chunks = self.knowledge_search.search(query, top_k, options)
        return self.rerank_stage.apply(query, chunks, top_k)

    @staticmethod
    def _chunk_to_source_item(chunk: RetrievedChunk) -> SourceItem:
        return SourceItem(
            file_name=chunk.file_name,
            page=chunk.page,
            content=chunk.content[:500],
        )

    # 以下兼容入口由冻结的7.1评估适配器和既有测试使用；行为委托给当前实现。
    @staticmethod
    def _build_retrieval_query(
        question: str,
        history: ChatHistory | None,
    ) -> str:
        return CurrentQueryBuilderAdapter().build(question, history)

    @staticmethod
    def _to_langchain_history(history: ChatHistory | None) -> list[BaseMessage]:
        return to_langchain_history(history)

    @staticmethod
    def _to_dashscope_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
        return to_dashscope_messages(messages)

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
