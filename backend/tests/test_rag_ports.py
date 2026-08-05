from collections.abc import AsyncIterator, Iterator
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.models import DocumentVersion, KnowledgeDocument
from app.modules.agent.contracts import AgentToolContext
from app.modules.agent.knowledge_tools import create_read_only_knowledge_registry
from app.modules.knowledge.public_catalog import PublishedKnowledgeCatalogService
from app.modules.knowledge.retrieval_eligibility import (
    EligibilityFilteredKnowledgeSearch,
    SqlAlchemyDocumentRetrievalEligibility,
)
from app.modules.rag.adapters import CurrentChromaKnowledgeSearchAdapter
from app.modules.rag.ports import (
    ChatHistory,
    GeneratedAnswer,
    GeneratedAnswerChunk,
    ModelUsage,
    RetrievedChunk,
)
from app.modules.rag.ports import KnowledgeSearchOptions, RetrievalMetadataFilter
from app.modules.rag.policies import RagRetrievalPolicy
from app.services.rag_service import INSUFFICIENT_KNOWLEDGE_MESSAGE, RagService


class FixedQueryBuilder:
    def __init__(self, query: str = "固定检索查询") -> None:
        self.query = query
        self.calls: list[tuple[str, ChatHistory | None]] = []

    def build(self, question: str, history: ChatHistory | None) -> str:
        self.calls.append((question, history))
        return self.query


class FixedKnowledgeSearch:
    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = chunks or []
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return self.chunks


class FixedAnswerGenerator:
    def __init__(self) -> None:
        self.answer_calls: list[tuple[str, ChatHistory | None, list[RetrievedChunk]]] = []
        self.stream_calls: list[tuple[str, ChatHistory | None, list[RetrievedChunk]]] = []
        self.astream_calls: list[tuple[str, ChatHistory | None, list[RetrievedChunk]]] = []

    def answer_with_usage(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> GeneratedAnswer:
        self.answer_calls.append((question, history, chunks))
        return GeneratedAnswer("固定回答", ModelUsage.actual(9, 2))

    def answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> str:
        self.answer_calls.append((question, history, chunks))
        return "固定回答"

    def stream_answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> Iterator[GeneratedAnswerChunk]:
        self.stream_calls.append((question, history, chunks))
        yield GeneratedAnswerChunk("固定")
        yield GeneratedAnswerChunk("")
        yield GeneratedAnswerChunk("回答", ModelUsage.actual(12, 3))

    async def astream_answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> AsyncIterator[GeneratedAnswerChunk]:
        self.astream_calls.append((question, history, chunks))
        yield GeneratedAnswerChunk("异步")
        yield GeneratedAnswerChunk("回答")
        yield GeneratedAnswerChunk("", ModelUsage.actual(15, 4))


class FixedOptionAwareKnowledgeSearch:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, int, object | None]] = []

    def search(self, query: str, top_k: int, options=None) -> list[RetrievedChunk]:
        self.calls.append((query, top_k, options))
        return self.chunks[:top_k]


def build_service(
    *, chunks: list[RetrievedChunk] | None = None
) -> tuple[RagService, FixedQueryBuilder, FixedKnowledgeSearch, FixedAnswerGenerator]:
    query_builder = FixedQueryBuilder()
    search = FixedKnowledgeSearch(chunks)
    answer = FixedAnswerGenerator()
    return (
        RagService(query_builder, search, answer),
        query_builder,
        search,
        answer,
    )


def test_query_builder_port_can_be_replaced_without_changing_orchestrator() -> None:
    chunk = RetrievedChunk("资料正文", "资料.txt", 2)
    service, query_builder, search, answer = build_service(chunks=[chunk])
    history = [("user", "上一问"), ("assistant", "上一答")]

    result, sources = service.ask("当前问题", 4, history)

    assert result == "固定回答"
    assert query_builder.calls == [("当前问题", history)]
    assert search.calls == [("固定检索查询", 4)]
    assert answer.answer_calls == [("当前问题", history, [chunk])]
    assert sources[0].model_dump() == {
        "file_name": "资料.txt",
        "page": 2,
        "content": "资料正文",
        "document_id": None,
        "chunk_id": None,
    }

    _, _, usage = service.ask_with_usage("当前问题", 4, history)
    assert usage == ModelUsage.actual(9, 2)


def test_knowledge_search_port_can_be_replaced_and_empty_result_keeps_refusal() -> None:
    service, query_builder, search, answer = build_service(chunks=[])

    result, sources = service.ask("当前问题", 4)

    assert result == INSUFFICIENT_KNOWLEDGE_MESSAGE
    assert sources == []
    assert query_builder.calls == [("当前问题", None)]
    assert search.calls == [("固定检索查询", 4)]
    assert answer.answer_calls == []


def test_answer_generator_port_can_be_replaced_for_sync_stream_and_async_stream() -> None:
    chunk = RetrievedChunk("资料正文", "资料.txt", None)
    service, _, _, answer = build_service(chunks=[chunk])

    stream_events = list(service.stream_ask("问题", 4))

    assert [event["data"] for event in stream_events] == [
        {"content": "固定"},
        {"content": "回答"},
        {
            "input_tokens": 12,
            "output_tokens": 3,
            "total_tokens": 15,
            "measurement": "actual",
        },
        {
            "sources": [
                {
                    "file_name": "资料.txt",
                    "page": None,
                    "content": "资料正文",
                    "document_id": None,
                    "chunk_id": None,
                }
            ]
        },
    ]
    assert answer.stream_calls == [("问题", None, [chunk])]


def test_answer_generator_async_port_keeps_token_then_sources_order() -> None:
    chunk = RetrievedChunk("资料正文", "资料.txt", None)
    service, _, _, answer = build_service(chunks=[chunk])

    async def collect_events() -> list[dict]:
        return [event async for event in service.astream_ask("问题", 4)]

    events = asyncio.run(collect_events())

    assert [event["event"] for event in events] == [
        "token",
        "token",
        "model_usage",
        "sources",
    ]
    assert [event["data"].get("content") for event in events[:2]] == ["异步", "回答"]
    assert answer.astream_calls == [("问题", None, [chunk])]


def test_zero_model_usage_precedes_public_refusal_content() -> None:
    service, _, _, _ = build_service(chunks=[])

    events = list(service.stream_ask("问题", 4))

    assert [event["event"] for event in events] == [
        "model_usage",
        "token",
        "sources",
    ]
    assert events[0]["data"]["measurement"] == "not_applicable"


def test_default_retrieval_policy_is_disabled_and_keeps_original_refusal() -> None:
    policy = RagRetrievalPolicy.from_settings(Settings(_env_file=None))

    assert policy.search_options.is_disabled is True
    assert policy.insufficient_knowledge_message == INSUFFICIENT_KNOWLEDGE_MESSAGE


def test_rag_settings_normalize_filters_and_validate_threshold() -> None:
    settings = Settings(
        _env_file=None,
        rag_filter_department="  心内科  ",
        rag_filter_topic=" ",
        rag_min_relevance_score=0.72,
        rag_insufficient_knowledge_message="  固定拒答  ",
    )
    policy = RagRetrievalPolicy.from_settings(settings)

    assert policy.search_options.metadata_filter.department == "心内科"
    assert policy.search_options.metadata_filter.topic is None
    assert policy.search_options.minimum_relevance_score == 0.72
    assert policy.insufficient_knowledge_message == "固定拒答"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_min_relevance_score=1.1)


def test_chroma_adapter_default_path_keeps_unscored_search_call() -> None:
    vector_store = Mock()
    vector_store.has_documents.return_value = True
    vector_store.similarity_search.return_value = [
        Document(
            page_content="片段",
            metadata={
                "document_id": "doc-1",
                "source": "目录/资料.txt",
                "page": 0,
            },
        )
    ]
    adapter = CurrentChromaKnowledgeSearchAdapter(vector_store)

    chunks = adapter.search("问题", 4)

    vector_store.similarity_search.assert_called_once_with("问题", 4)
    vector_store.similarity_search_with_relevance_scores.assert_not_called()
    assert chunks == [
        RetrievedChunk(
            content="片段",
            file_name="资料.txt",
            page=1,
            document_id="doc-1",
            relevance_score=None,
            metadata={
                "document_id": "doc-1",
                "source": "目录/资料.txt",
                "page": 0,
            },
        )
    ]


def test_chroma_adapter_applies_metadata_filter_and_minimum_score() -> None:
    vector_store = Mock()
    vector_store.has_documents.return_value = True
    accepted = Document(
        page_content="高分片段",
        metadata={"document_id": "doc-1", "file_name": "高分.txt"},
    )
    rejected = Document(
        page_content="低分片段",
        metadata={"document_id": "doc-2", "file_name": "低分.txt"},
    )
    vector_store.similarity_search_with_relevance_scores.return_value = [
        (accepted, 0.81),
        (rejected, 0.69),
    ]
    adapter = CurrentChromaKnowledgeSearchAdapter(vector_store)
    options = KnowledgeSearchOptions(
        metadata_filter=RetrievalMetadataFilter(
            department="心内科",
            document_type="txt",
        ),
        minimum_relevance_score=0.7,
    )

    chunks = adapter.search("问题", 4, options)

    vector_store.similarity_search_with_relevance_scores.assert_called_once_with(
        "问题",
        4,
        {
            "$and": [
                {"department": {"$eq": "心内科"}},
                {"document_type": {"$eq": "txt"}},
            ]
        },
    )
    assert [chunk.document_id for chunk in chunks] == ["doc-1"]
    assert chunks[0].relevance_score == 0.81


def test_no_qualified_context_uses_configured_refusal_without_answer_call() -> None:
    class OptionsAwareSearch:
        def __init__(self) -> None:
            self.options = None

        def search(self, query, top_k, options=None):
            self.options = options
            return []

    search = OptionsAwareSearch()
    answer = FixedAnswerGenerator()
    policy = RagRetrievalPolicy(
        search_options=KnowledgeSearchOptions(minimum_relevance_score=0.75),
        insufficient_knowledge_message="未找到达到阈值的知识库资料。",
    )
    service = RagService(FixedQueryBuilder(), search, answer, policy)

    result, sources = service.ask("问题", 4)

    assert result == "未找到达到阈值的知识库资料。"
    assert sources == []
    assert search.options == policy.search_options
    assert answer.answer_calls == []


def test_retrieval_eligibility_filters_expired_and_overfetches_without_n_plus_one() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as session:
        for document_id, status, expires_at in (
            ("doc-expired", "published", now - timedelta(seconds=1)),
            ("doc-archived", "archived", None),
            ("doc-current", "published", now + timedelta(days=1)),
            ("doc-current-2", "ready", None),
        ):
            session.add(
                KnowledgeDocument(
                    id=document_id,
                    original_name=f"{document_id}.txt",
                    stored_name=f"{document_id}.txt",
                    content_hash=hashlib.sha256(document_id.encode("utf-8")).hexdigest(),
                    size_bytes=10,
                    chunk_count=1,
                    chunk_ids=[f"{document_id}:0"],
                    uploader_id=None,
                    is_system=True,
                    status=status,
                )
            )
            session.add(
                DocumentVersion(
                    id=f"version-{document_id}",
                    document_id=document_id,
                    version=1,
                    source="system",
                    tags=[],
                    expires_at=expires_at,
                    review_status="current",
                )
            )
        session.commit()
        search = FixedOptionAwareKnowledgeSearch(
            [
                RetrievedChunk("过期", "a.txt", None, document_id="doc-expired"),
                RetrievedChunk("归档", "b.txt", None, document_id="doc-archived"),
                RetrievedChunk("有效1", "c.txt", None, document_id="doc-current"),
                RetrievedChunk("有效2", "d.txt", None, document_id="doc-current-2"),
            ]
        )
        filtered = EligibilityFilteredKnowledgeSearch(
            search,
            SqlAlchemyDocumentRetrievalEligibility(session, now=now),
            overfetch_factor=4,
            overfetch_extra=8,
            overfetch_max=50,
        )

        chunks = filtered.search("问题", 2)

        assert [chunk.document_id for chunk in chunks] == ["doc-current", "doc-current-2"]
        assert search.calls == [("问题", 10, None)]
    engine.dispose()


def test_agent_tool_and_catalog_share_expired_retrieval_eligibility() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as session:
        for document_id, expires_at in (
            ("doc-expired", now - timedelta(seconds=1)),
            ("doc-current", None),
        ):
            session.add(
                KnowledgeDocument(
                    id=document_id,
                    original_name=f"{document_id}.txt",
                    stored_name=f"{document_id}.txt",
                    content_hash=hashlib.sha256(document_id.encode("utf-8")).hexdigest(),
                    size_bytes=10,
                    chunk_count=1,
                    chunk_ids=[f"{document_id}:0"],
                    uploader_id=None,
                    is_system=True,
                    status="published",
                )
            )
            session.add(
                DocumentVersion(
                    id=f"version-{document_id}",
                    document_id=document_id,
                    version=1,
                    source="system",
                    tags=[],
                    expires_at=expires_at,
                    review_status="current",
                )
            )
        session.commit()
        search = EligibilityFilteredKnowledgeSearch(
            FixedOptionAwareKnowledgeSearch(
                [
                    RetrievedChunk("过期", "a.txt", None, document_id="doc-expired"),
                    RetrievedChunk("有效", "b.txt", None, document_id="doc-current"),
                ]
            ),
            SqlAlchemyDocumentRetrievalEligibility(session, now=now),
        )
        registry = create_read_only_knowledge_registry(
            search,
            PublishedKnowledgeCatalogService(session),
        )
        context = AgentToolContext(run_id="run-1", user_id="user-1")

        search_result = registry.invoke(
            "search_knowledge",
            context,
            {"query": "患者安全", "top_k": 2},
        )
        expired_info = registry.invoke(
            "get_document_info",
            context,
            {"document_id": "doc-expired"},
        )

        assert search_result.source_ids == ["doc-current"]
        assert expired_info.data == {"found": False}
    engine.dispose()
