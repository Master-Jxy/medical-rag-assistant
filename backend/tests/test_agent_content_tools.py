"""任务11.5：摘要、比较和学习报告产物。"""

from datetime import datetime, timezone

from app.modules.agent.contracts import AgentToolContext
from app.modules.agent.generation import GeneratedAgentText
from app.modules.agent.knowledge_tools import create_read_only_knowledge_registry
from app.modules.knowledge.public_ports import (
    PublishedDocumentContent,
    PublishedDocumentInfo,
)


class FakeSearch:
    def search(self, query, top_k, options=None):
        return []


class FakeCatalog:
    def __init__(self):
        self.documents = {
            "doc-1": PublishedDocumentContent(
                "doc-1", "指南A.pdf", "资料A正文", 2, ()
            ),
            "doc-2": PublishedDocumentContent(
                "doc-2", "指南B.pdf", "资料B正文", 3, ("存在表格",)
            ),
        }

    def get_published_document(self, document_id):
        content = self.documents.get(document_id)
        if not content:
            return None
        return PublishedDocumentInfo(
            content.document_id,
            content.file_name,
            "published",
            None,
            (),
            1,
            2,
            datetime.now(timezone.utc),
        )

    def get_published_content(self, document_id):
        return self.documents.get(document_id)


class FakeGenerator:
    def summarize(self, document, focus):
        return GeneratedAgentText(f"摘要：{document.file_name}；关注：{focus}", 10, 0.001)

    def compare(self, documents, dimensions):
        return GeneratedAgentText(
            f"比较：{','.join(item.file_name for item in documents)}；"
            f"维度：{','.join(dimensions)}",
            20,
            0.002,
        )

    def learning_report(self, *, title, learning_goal, documents):
        sources = "\n".join(
            f"- [{item.document_id}] {item.file_name}" for item in documents
        )
        return GeneratedAgentText(
            f"# {title}\n\n目标：{learning_goal}\n\n## 来源\n{sources}",
            30,
            0.003,
        )


def registry():
    return create_read_only_knowledge_registry(
        FakeSearch(),
        FakeCatalog(),
        FakeGenerator(),
    )


def test_summary_and_compare_keep_sources_and_usage() -> None:
    context = AgentToolContext("run-1", "user-1")
    summary = registry().invoke(
        "summarize_document",
        context,
        {"document_id": "doc-1", "focus": "安全"},
    )
    assert summary.source_ids == ["doc-1"]
    assert summary.used_tokens == 10
    assert summary.estimated_cost_cny == 0.001

    comparison = registry().invoke(
        "compare_documents",
        context,
        {"document_ids": ["doc-1", "doc-2"], "dimensions": ["适用范围"]},
    )
    assert comparison.source_ids == ["doc-1", "doc-2"]
    assert "适用范围" in comparison.summary


def test_report_is_a_downloadable_markdown_artifact() -> None:
    result = registry().invoke(
        "generate_learning_report",
        AgentToolContext(
            "run-1",
            "user-1",
            (
                "[当前任务]\n补充上一轮报告\n\n"
                "[显式引用产物]\n上一轮.md\n内容摘录：重点风险"
            ),
        ),
        {
            "title": "患者/安全 学习",
            "learning_goal": "理解核查流程",
            "document_ids": ["doc-1", "doc-2"],
        },
    )
    assert result.summary == "已生成学习报告《患者/安全 学习》"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.file_name == "患者-安全-学习.md"
    assert artifact.mime_type == "text/markdown"
    assert artifact.source_ids == ["doc-1", "doc-2"]
    assert "# 患者/安全 学习" in artifact.content
    assert "显式引用产物" in artifact.content
    assert "内容摘录：重点风险" in artifact.content


def test_content_tools_refuse_partial_or_unpublished_inputs() -> None:
    result = registry().invoke(
        "compare_documents",
        AgentToolContext("run-1", "user-1"),
        {"document_ids": ["doc-1", "doc-private"], "dimensions": []},
    )
    assert result.source_ids == []
    assert result.data == {"missing_document_ids": ["doc-private"]}
    assert "未执行" in result.summary
