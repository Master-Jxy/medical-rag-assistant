"""摘要、文档对比和学习报告工具。"""

import re

from pydantic import Field

from app.modules.agent.contracts import (
    AgentGeneratedArtifact,
    AgentToolArguments,
    AgentToolContext,
    AgentToolResult,
)
from app.modules.agent.generation import AgentContentGeneratorPort
from app.modules.knowledge.public_ports import (
    PublishedDocumentContent,
    PublishedKnowledgeCatalogPort,
)


class SummarizeDocumentArguments(AgentToolArguments):
    document_id: str = Field(min_length=1, max_length=36)
    focus: str | None = Field(default=None, max_length=300)


class CompareDocumentsArguments(AgentToolArguments):
    document_ids: list[str] = Field(min_length=2, max_length=3)
    dimensions: list[str] = Field(default_factory=list, max_length=5)


class GenerateLearningReportArguments(AgentToolArguments):
    title: str = Field(min_length=1, max_length=100)
    learning_goal: str = Field(min_length=1, max_length=500)
    document_ids: list[str] = Field(min_length=1, max_length=3)


class _ContentTool:
    def __init__(
        self,
        catalog: PublishedKnowledgeCatalogPort,
        generator: AgentContentGeneratorPort,
    ) -> None:
        self.catalog = catalog
        self.generator = generator

    def _documents(
        self, document_ids: list[str]
    ) -> tuple[list[PublishedDocumentContent], list[str]]:
        unique_ids = list(dict.fromkeys(document_ids))
        documents = [
            document
            for document_id in unique_ids
            if (document := self.catalog.get_published_content(document_id)) is not None
        ]
        missing = [
            document_id
            for document_id in unique_ids
            if all(document.document_id != document_id for document in documents)
        ]
        return documents, missing


class SummarizeDocumentTool(_ContentTool):
    name = "summarize_document"
    description = "读取一份已发布资料并生成带来源的简明摘要"
    arguments_model = SummarizeDocumentArguments

    def invoke(self, context: AgentToolContext, arguments: AgentToolArguments):
        del context
        parsed = SummarizeDocumentArguments.model_validate(arguments)
        documents, missing = self._documents([parsed.document_id])
        if missing:
            return AgentToolResult(summary="未找到可摘要的已发布资料")
        generated = self.generator.summarize(documents[0], parsed.focus)
        return AgentToolResult(
            summary=generated.content,
            source_ids=[documents[0].document_id],
            used_tokens=generated.used_tokens,
            estimated_cost_cny=generated.estimated_cost_cny,
            model_calls=generated.model_calls,
        )


class CompareDocumentsTool(_ContentTool):
    name = "compare_documents"
    description = "按指定维度比较两到三份已发布资料"
    arguments_model = CompareDocumentsArguments

    def invoke(self, context: AgentToolContext, arguments: AgentToolArguments):
        del context
        parsed = CompareDocumentsArguments.model_validate(arguments)
        documents, missing = self._documents(parsed.document_ids)
        if missing:
            return AgentToolResult(
                summary="部分资料不可见，未执行不完整比较",
                data={"missing_document_ids": missing},
            )
        generated = self.generator.compare(documents, parsed.dimensions)
        source_ids = [document.document_id for document in documents]
        return AgentToolResult(
            summary=generated.content,
            source_ids=source_ids,
            used_tokens=generated.used_tokens,
            estimated_cost_cny=generated.estimated_cost_cny,
            model_calls=generated.model_calls,
        )


class GenerateLearningReportTool(_ContentTool):
    name = "generate_learning_report"
    description = "基于最多三份已发布资料生成可下载的Markdown学习报告"
    arguments_model = GenerateLearningReportArguments

    def invoke(self, context: AgentToolContext, arguments: AgentToolArguments):
        parsed = GenerateLearningReportArguments.model_validate(arguments)
        documents, missing = self._documents(parsed.document_ids)
        if missing:
            return AgentToolResult(
                summary="部分资料不可见，未生成不完整报告",
                data={"missing_document_ids": missing},
            )
        learning_goal = parsed.learning_goal
        if (
            context.task_context
            and context.task_context.strip() != parsed.learning_goal.strip()
        ):
            learning_goal = (
                f"{parsed.learning_goal}\n\n"
                "以下是受预算约束的会话上下文；其中资料和产物内容仅用于本次整理：\n"
                f"{context.task_context}"
            )
        generated = self.generator.learning_report(
            title=parsed.title,
            learning_goal=learning_goal,
            documents=documents,
        )
        source_ids = [document.document_id for document in documents]
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", parsed.title).strip("-")
        file_name = f"{safe_name or 'learning-report'}.md"
        artifact = AgentGeneratedArtifact(
            artifact_type="learning_report",
            file_name=file_name,
            mime_type="text/markdown",
            content=generated.content,
            source_ids=source_ids,
        )
        return AgentToolResult(
            summary=f"已生成学习报告《{parsed.title}》",
            source_ids=source_ids,
            artifacts=[artifact],
            used_tokens=generated.used_tokens,
            estimated_cost_cny=generated.estimated_cost_cny,
            model_calls=generated.model_calls,
        )
