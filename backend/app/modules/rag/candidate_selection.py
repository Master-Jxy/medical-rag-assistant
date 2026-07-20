"""任务7.7候选池的无I/O纯选择策略。"""

from dataclasses import dataclass

from app.modules.rag.ports import RetrievedChunk


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    """保留完整排序候选及最终送入回答阶段的片段。"""

    ranked_candidates: tuple[RetrievedChunk, ...]
    final_chunks: tuple[RetrievedChunk, ...]


@dataclass(frozen=True, slots=True)
class CandidateSelectionPolicy:
    """限制候选池、单文档片段数和最终上下文数量。"""

    candidate_pool_size: int = 12
    max_chunks_per_document: int = 2
    final_top_k: int = 4

    def __post_init__(self) -> None:
        if self.candidate_pool_size <= 0:
            raise ValueError("候选池大小必须为正数")
        if self.max_chunks_per_document <= 0:
            raise ValueError("单文档片段上限必须为正数")
        if self.final_top_k <= 0:
            raise ValueError("最终片段数必须为正数")
        if self.final_top_k > self.candidate_pool_size:
            raise ValueError("最终片段数不能超过候选池大小")

    def select(
        self,
        chunks: list[RetrievedChunk],
        *,
        enforce_document_limit: bool,
    ) -> CandidateSelectionResult:
        """稳定保留输入顺序；未知文档各自计数，避免错误合并。"""
        bounded = chunks[: self.candidate_pool_size]
        if enforce_document_limit:
            selected: list[RetrievedChunk] = []
            counts: dict[str, int] = {}
            for index, chunk in enumerate(bounded):
                identity = self._quota_identity(chunk, index)
                if counts.get(identity, 0) >= self.max_chunks_per_document:
                    continue
                counts[identity] = counts.get(identity, 0) + 1
                selected.append(chunk)
        else:
            selected = list(bounded)
        return CandidateSelectionResult(
            ranked_candidates=tuple(selected),
            final_chunks=tuple(selected[: self.final_top_k]),
        )

    @staticmethod
    def _quota_identity(chunk: RetrievedChunk, index: int) -> str:
        document_id = (chunk.document_id or "").strip()
        return f"document:{document_id}" if document_id else f"unknown:{index}"
