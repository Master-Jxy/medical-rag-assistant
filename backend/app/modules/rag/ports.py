"""RAG 内部可替换能力的稳定契约。"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Protocol, TypeAlias

from app.core.enums import StrEnum

ChatHistory = list[tuple[str, str]]
MetadataValue: TypeAlias = str | int | float | bool


@dataclass(frozen=True, slots=True)
class RetrievalMetadataFilter:
    """允许进入Chroma查询边界的受控元数据条件。"""

    department: str | None = None
    topic: str | None = None
    document_type: str | None = None
    knowledge_base_version: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "department",
            "topic",
            "document_type",
            "knowledge_base_version",
        ):
            value = getattr(self, field_name)
            if value is not None and (not value.strip() or len(value) > 100):
                raise ValueError(f"检索元数据 {field_name} 必须为1-100个非空字符")

    def as_items(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (field_name, value.strip())
            for field_name in (
                "department",
                "topic",
                "document_type",
                "knowledge_base_version",
            )
            if (value := getattr(self, field_name)) is not None
        )


@dataclass(frozen=True, slots=True)
class KnowledgeSearchOptions:
    """可关闭的过滤与最低相关度策略；默认值保持原检索行为。"""

    metadata_filter: RetrievalMetadataFilter = field(
        default_factory=RetrievalMetadataFilter
    )
    minimum_relevance_score: float | None = None

    def __post_init__(self) -> None:
        score = self.minimum_relevance_score
        if score is not None and not 0 <= score <= 1:
            raise ValueError("最低相关度必须位于0到1之间")

    @property
    def is_disabled(self) -> bool:
        return not self.metadata_filter.as_items() and self.minimum_relevance_score is None


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """与 Chroma/LangChain 对象解耦的统一检索结果。"""

    content: str
    file_name: str
    page: int | None
    chunk_id: str | None = None
    document_id: str | None = None
    relevance_score: float | None = None
    metadata: dict[str, MetadataValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RerankUsage:
    """一次重排调用的脱敏计量，不包含查询或文档正文。"""

    request_count: int
    input_tokens: int
    estimated_cost_cny: float


@dataclass(frozen=True, slots=True)
class RerankResult:
    """厂商无关的重排结果与计量。"""

    chunks: list[RetrievedChunk]
    usage: RerankUsage


class TokenMeasurement(StrEnum):
    ACTUAL = "actual"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    measurement: TokenMeasurement

    @classmethod
    def actual(cls, input_tokens: int, output_tokens: int) -> "ModelUsage":
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token计量不能为负数")
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            measurement=TokenMeasurement.ACTUAL,
        )

    @classmethod
    def unknown(cls) -> "ModelUsage":
        return cls(None, None, None, TokenMeasurement.UNKNOWN)

    @classmethod
    def not_applicable(cls) -> "ModelUsage":
        return cls(0, 0, 0, TokenMeasurement.NOT_APPLICABLE)

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "measurement": self.measurement.value,
        }


@dataclass(frozen=True, slots=True)
class GeneratedAnswerChunk:
    content: str
    usage: ModelUsage | None = None


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    content: str
    usage: ModelUsage


class QueryBuilderPort(Protocol):
    """根据当前问题和历史生成知识库检索查询。"""

    def build(self, question: str, history: ChatHistory | None) -> str: ...


class KnowledgeSearchPort(Protocol):
    """执行知识检索并返回统一片段。"""

    def search(
        self,
        query: str,
        top_k: int,
        options: KnowledgeSearchOptions | None = None,
    ) -> list[RetrievedChunk]: ...


class KeywordSearchPort(Protocol):
    """执行不依赖Embedding的关键词检索。"""

    def search(
        self,
        query: str,
        top_k: int,
        options: KnowledgeSearchOptions | None = None,
    ) -> list[RetrievedChunk]: ...


class RerankPort(Protocol):
    """对已召回片段重新排序，不负责召回或回答生成。"""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_n: int,
    ) -> RerankResult: ...


class AnswerGeneratorPort(Protocol):
    """使用问题、历史和检索上下文生成普通或流式回答。"""

    def answer_with_usage(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> GeneratedAnswer: ...

    def answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> str: ...

    def stream_answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> Iterator[GeneratedAnswerChunk]: ...

    def astream_answer(
        self,
        question: str,
        history: ChatHistory | None,
        chunks: list[RetrievedChunk],
    ) -> AsyncIterator[GeneratedAnswerChunk]: ...
