"""Agent可调用的公共知识只读工具。"""

from pydantic import Field

from app.modules.agent.contracts import (
    AgentToolArguments,
    AgentToolContext,
    AgentToolResult,
)
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.content_tools import (
    CompareDocumentsTool,
    GenerateLearningReportTool,
    SummarizeDocumentTool,
)
from app.modules.agent.generation import AgentContentGeneratorPort
from app.modules.knowledge.public_ports import PublishedKnowledgeCatalogPort
from app.modules.rag.ports import KnowledgeSearchPort


class SearchKnowledgeArguments(AgentToolArguments):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class GetDocumentInfoArguments(AgentToolArguments):
    document_id: str = Field(min_length=1, max_length=36)


class SearchKnowledgeTool:
    name = "search_knowledge"
    description = "从已发布公共知识库检索与任务相关的资料片段"
    arguments_model = SearchKnowledgeArguments

    def __init__(self, search: KnowledgeSearchPort) -> None:
        self.search = search

    def invoke(
        self,
        context: AgentToolContext,
        arguments: AgentToolArguments,
    ) -> AgentToolResult:
        del context
        parsed = SearchKnowledgeArguments.model_validate(arguments)
        chunks = self.search.search(parsed.query, parsed.top_k)
        items: list[dict[str, object]] = []
        source_ids: list[str] = []
        for chunk in chunks:
            source_id = chunk.document_id or chunk.chunk_id
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
            items.append(
                {
                    "content": chunk.content[:2000],
                    "file_name": chunk.file_name,
                    "page": chunk.page,
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "relevance_score": chunk.relevance_score,
                }
            )
        return AgentToolResult(
            summary=f"检索到 {len(items)} 个已发布知识片段",
            source_ids=source_ids,
            data={"items": items, "count": len(items)},
        )


class GetDocumentInfoTool:
    name = "get_document_info"
    description = "读取一份已发布公共知识文档的安全元数据"
    arguments_model = GetDocumentInfoArguments

    def __init__(self, catalog: PublishedKnowledgeCatalogPort) -> None:
        self.catalog = catalog

    def invoke(
        self,
        context: AgentToolContext,
        arguments: AgentToolArguments,
    ) -> AgentToolResult:
        del context
        parsed = GetDocumentInfoArguments.model_validate(arguments)
        document = self.catalog.get_published_document(parsed.document_id)
        if document is None:
            return AgentToolResult(
                summary="未找到可见的已发布资料",
                data={"found": False},
            )
        return AgentToolResult(
            summary=f"已读取已发布资料《{document.file_name}》",
            source_ids=[document.document_id],
            data={
                "found": True,
                "document_id": document.document_id,
                "file_name": document.file_name,
                "status": document.status,
                "source": document.source,
                "tags": list(document.tags),
                "version": document.version,
                "chunk_count": document.chunk_count,
                "created_at": document.created_at.isoformat(),
            },
        )


def create_read_only_knowledge_registry(
    search: KnowledgeSearchPort,
    catalog: PublishedKnowledgeCatalogPort,
    generator: AgentContentGeneratorPort | None = None,
) -> ToolRegistry:
    tools = [
        SearchKnowledgeTool(search),
        GetDocumentInfoTool(catalog),
    ]
    if generator is not None:
        tools.extend(
            [
                SummarizeDocumentTool(catalog, generator),
                CompareDocumentsTool(catalog, generator),
                GenerateLearningReportTool(catalog, generator),
            ]
        )
    return ToolRegistry(tools)
