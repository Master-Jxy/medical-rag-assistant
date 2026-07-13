"""集中封装 Chroma 操作，路由和 RAG 服务不直接操作数据库。"""

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.core.config import Settings, get_settings
from app.core.model_factory import create_embedding_model


class VectorStoreService:
    """提供知识库状态检查和相似片段检索。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.vector_store = Chroma(
            collection_name=self.settings.chroma_collection_name,
            embedding_function=create_embedding_model(self.settings),
            persist_directory=str(self.settings.chroma_persist_dir),
        )

    def has_documents(self) -> bool:
        """先判断知识库是否为空；空库时不调用 Embedding，避免无效计费。"""
        result = self.vector_store.get(limit=1, include=[])
        return bool(result.get("ids"))

    def similarity_search(self, query: str, top_k: int) -> list[Document]:
        """把问题向量化，并返回最相关的 top_k 个知识片段。"""
        return self.vector_store.similarity_search(query=query, k=top_k)

    def add_documents(self, documents: list[Document], ids: list[str]) -> None:
        """把已切分片段向量化后写入 Chroma。"""
        self.vector_store.add_documents(documents=documents, ids=ids)

    def delete_documents(self, ids: list[str]) -> None:
        """按片段 ID 删除向量，可用于文档删除或失败回滚。"""
        if ids:
            self.vector_store.delete(ids=ids)

    def contains_ids(self, ids: list[str]) -> bool:
        """检查指定片段是否仍在 Chroma 中，主要用于删除结果验证。"""
        if not ids:
            return False
        result = self.vector_store.get(ids=ids, include=[])
        return bool(result.get("ids"))
