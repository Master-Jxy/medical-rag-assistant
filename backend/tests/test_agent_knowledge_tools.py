"""任务11.3：Agent只读知识工具与公共知识目录。"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import DocumentVersion, KnowledgeDocument
from app.modules.agent.contracts import AgentToolContext
from app.modules.agent.knowledge_tools import create_read_only_knowledge_registry
from app.modules.knowledge.public_catalog import PublishedKnowledgeCatalogService
from app.modules.rag.ports import RetrievedChunk


class FakeKnowledgeSearch:
    def search(self, query: str, top_k: int, options=None):
        assert query == "患者安全"
        assert top_k == 2
        assert options is None
        return [
            RetrievedChunk(
                content="术前应完成身份核对。",
                file_name="患者安全.pdf",
                page=3,
                chunk_id="chunk-1",
                document_id="doc-published",
                relevance_score=0.92,
            )
        ]


def build_document(document_id: str, status: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=document_id,
        original_name=f"{document_id}.pdf",
        stored_name=f"{document_id}.pdf",
        content_hash=(document_id[-1] * 64),
        size_bytes=100,
        chunk_count=2,
        chunk_ids=[f"{document_id}-chunk"],
        uploader_id=None,
        is_system=True,
        status=status,
    )


def test_tools_return_structured_public_results() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        published = build_document("doc-published", "published")
        session.add(published)
        session.add(
            DocumentVersion(
                id="version-1",
                document_id=published.id,
                version=2,
                source="指南",
                tags=["手术", "安全"],
            )
        )
        session.commit()

        registry = create_read_only_knowledge_registry(
            FakeKnowledgeSearch(),
            PublishedKnowledgeCatalogService(session),
        )
        context = AgentToolContext(run_id="run-1", user_id="user-1")

        search_result = registry.invoke(
            "search_knowledge",
            context,
            {"query": "患者安全", "top_k": 2},
        )
        assert search_result.source_ids == ["doc-published"]
        assert search_result.data["count"] == 1
        assert search_result.data["items"][0]["page"] == 3

        info_result = registry.invoke(
            "get_document_info",
            context,
            {"document_id": "doc-published"},
        )
        assert info_result.source_ids == ["doc-published"]
        assert info_result.data["version"] == 2
        assert info_result.data["tags"] == ["手术", "安全"]
    engine.dispose()


def test_catalog_hides_archived_and_missing_documents() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(build_document("doc-archived", "archived"))
        session.commit()
        registry = create_read_only_knowledge_registry(
            FakeKnowledgeSearch(),
            PublishedKnowledgeCatalogService(session),
        )
        context = AgentToolContext(run_id="run-1", user_id="user-1")

        for document_id in ("doc-archived", "doc-missing"):
            result = registry.invoke(
                "get_document_info",
                context,
                {"document_id": document_id},
            )
            assert result.source_ids == []
            assert result.data == {"found": False}
    engine.dispose()
