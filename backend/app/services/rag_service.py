"""普通 RAG 应用服务：编排查询构造、知识检索和回答生成。"""

import asyncio
from pathlib import Path
from time import monotonic

from fastapi import Request
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage

from app.core.exceptions import ConfigurationError, RagServiceError
from app.core.config import get_settings
from app.core.request_context import get_request_id
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
    GeneratedAnswer,
    GeneratedAnswerChunk,
    KnowledgeSearchPort,
    ModelUsage,
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
from app.ports.telemetry import NullTelemetry, TelemetryEvent, TelemetryPort, emit_safely

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
        telemetry: TelemetryPort | None = None,
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
            self.telemetry = telemetry or NullTelemetry()
            self.model_name = settings.chat_model_name
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

    def ask(
        self,
        question: str,
        top_k: int,
        history: ChatHistory | None = None,
    ) -> tuple[str, list[SourceItem]]:
        """输入问题，输出模型回答和结构化引用来源。"""
        answer, sources, _ = self.ask_with_usage(question, top_k, history)
        return answer, sources

    def ask_with_usage(
        self,
        question: str,
        top_k: int,
        history: ChatHistory | None = None,
    ) -> tuple[str, list[SourceItem], ModelUsage]:
        """同步回答并返回厂商无关计量；保留ask的既有公开契约。"""
        try:
            chunks = self._retrieve_chunks(question, top_k, history)
            if not chunks:
                usage = ModelUsage.not_applicable()
                self._emit_model_generation(monotonic(), "skipped", usage=usage)
                return self.retrieval_policy.insufficient_knowledge_message, [], usage
            started = monotonic()
            result = "failure"
            error_type = None
            usage = ModelUsage.unknown()
            try:
                answer_with_usage = getattr(
                    self.answer_generator, "answer_with_usage", None
                )
                if answer_with_usage is None:
                    generated = GeneratedAnswer(
                        content=self.answer_generator.answer(question, history, chunks),
                        usage=ModelUsage.unknown(),
                    )
                else:
                    generated = answer_with_usage(question, history, chunks)
                answer = generated.content
                usage = generated.usage
                result = "success"
            except Exception as exc:
                error_type = type(exc).__name__
                raise
            finally:
                self._emit_model_generation(
                    started,
                    result,
                    error_type=error_type,
                    usage=usage,
                )
            return (
                answer,
                [self._chunk_to_source_item(chunk) for chunk in chunks],
                usage,
            )
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
                usage = ModelUsage.not_applicable()
                yield {"event": "model_usage", "data": usage.as_dict()}
                yield {
                    "event": "token",
                    "data": {
                        "content": self.retrieval_policy.insufficient_knowledge_message
                    },
                }
                yield {"event": "sources", "data": {"sources": []}}
                self._emit_model_generation(
                    monotonic(), "skipped", usage=usage
                )
                return

            started = monotonic()
            result = "failure"
            error_type = None
            usage = ModelUsage.unknown()
            try:
                for chunk in self.answer_generator.stream_answer(
                    question, history, chunks
                ):
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if chunk.content:
                        yield {
                            "event": "token",
                            "data": {"content": chunk.content},
                        }
                result = "success"
                yield {"event": "model_usage", "data": usage.as_dict()}
            except BaseException as exc:
                error_type = type(exc).__name__
                result = "stopped" if isinstance(exc, GeneratorExit) else "failure"
                raise
            finally:
                self._emit_model_generation(
                    started,
                    result,
                    error_type=error_type,
                    usage=usage,
                )
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
                usage = ModelUsage.not_applicable()
                yield {"event": "model_usage", "data": usage.as_dict()}
                yield {
                    "event": "token",
                    "data": {
                        "content": self.retrieval_policy.insufficient_knowledge_message
                    },
                }
                yield {"event": "sources", "data": {"sources": []}}
                self._emit_model_generation(
                    monotonic(), "skipped", usage=usage
                )
                return

            started = monotonic()
            result = "failure"
            error_type = None
            usage = ModelUsage.unknown()
            try:
                async for chunk in self.answer_generator.astream_answer(
                    question, history, chunks
                ):
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if chunk.content:
                        yield {
                            "event": "token",
                            "data": {"content": chunk.content},
                        }
                result = "success"
                yield {"event": "model_usage", "data": usage.as_dict()}
            except BaseException as exc:
                error_type = type(exc).__name__
                result = (
                    "stopped"
                    if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
                    else "failure"
                )
                raise
            finally:
                self._emit_model_generation(
                    started,
                    result,
                    error_type=error_type,
                    usage=usage,
                )
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
        started = monotonic()
        try:
            query = self.query_builder.build(question, history)
        except Exception as exc:
            self._emit_stage(
                "query_construction",
                started,
                "failure",
                error_type=type(exc).__name__,
            )
            raise
        self._emit_stage("query_construction", started, "success")
        options = self.retrieval_policy.search_options
        started = monotonic()
        try:
            if options.is_disabled:
                chunks = self.knowledge_search.search(query, top_k)
            else:
                chunks = self.knowledge_search.search(query, top_k, options)
        except Exception as exc:
            self._emit_stage(
                "knowledge_retrieval",
                started,
                "failure",
                error_type=type(exc).__name__,
            )
            raise
        self._emit_stage(
            "knowledge_retrieval",
            started,
            "success",
            retrieved_chunk_count=len(chunks),
        )
        started = monotonic()
        try:
            reranked = self.rerank_stage.apply(query, chunks, top_k)
        except Exception as exc:
            self._emit_stage(
                "rerank",
                started,
                "failure",
                error_type=type(exc).__name__,
            )
            raise
        self._emit_stage(
            "rerank",
            started,
            "success" if self.rerank_stage.policy.enabled else "skipped",
            retrieved_chunk_count=len(reranked),
        )
        return reranked

    def _emit_stage(
        self,
        stage: str,
        started: float,
        result: str,
        **fields,
    ) -> None:
        emit_safely(
            self.telemetry,
            TelemetryEvent.create(
                request_id=get_request_id(),
                event_name="rag_stage",
                result=result,
                stage=stage,
                duration_ms=round((monotonic() - started) * 1000, 3),
                **fields,
            ),
        )

    def _emit_model_generation(
        self,
        started: float,
        result: str,
        *,
        usage: ModelUsage,
        error_type: str | None = None,
    ) -> None:
        self._emit_stage(
            "model_generation",
            started,
            result,
            error_type=error_type,
            model_name=self.model_name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            token_measurement=usage.measurement.value,
        )

    @staticmethod
    def _chunk_to_source_item(chunk: RetrievedChunk) -> SourceItem:
        return SourceItem(
            file_name=chunk.file_name,
            page=chunk.page,
            content=chunk.content[:500],
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
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


def get_rag_service(request: Request) -> RagService:
    """第一次聊天请求时创建服务，之后复用模型和 Chroma 连接。"""
    service = getattr(request.app.state, "rag_service", None)
    if service is None:
        service = RagService(telemetry=request.app.state.telemetry)
        request.app.state.rag_service = service
    return service
