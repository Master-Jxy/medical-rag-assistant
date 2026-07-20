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

    def similarity_search(
        self,
        query: str,
        top_k: int,
        metadata_filter: dict | None = None,
    ) -> list[Document]:
        """把问题向量化，并返回最相关的 top_k 个知识片段。"""
        if metadata_filter:
            return self.vector_store.similarity_search(
                query=query, k=top_k, filter=metadata_filter
            )
        return self.vector_store.similarity_search(query=query, k=top_k)

    def similarity_search_with_relevance_scores(
        self,
        query: str,
        top_k: int,
        metadata_filter: dict | None = None,
    ) -> list[tuple[Document, float]]:
        """只在显式启用最低相关度时读取归一化相关度分数。"""
        kwargs = {"query": query, "k": top_k}
        if metadata_filter:
            kwargs["filter"] = metadata_filter
        return self.vector_store.similarity_search_with_relevance_scores(**kwargs)

    def list_documents(
        self,
        metadata_filter: dict | None = None,
    ) -> list[tuple[str, Document]]:
        """只读列出匹配片段，供本地关键词检索使用，不调用Embedding。"""
        kwargs = {"include": ["documents", "metadatas"]}
        if metadata_filter:
            kwargs["where"] = metadata_filter
        result = self.vector_store.get(**kwargs)
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        return [
            (
                str(chunk_id),
                Document(
                    page_content=str(content or ""),
                    metadata=dict(metadata or {}),
                ),
            )
            for chunk_id, content, metadata in zip(
                ids, documents, metadatas, strict=True
            )
            if str(content or "").strip()
        ]

    def add_documents(self, documents: list[Document], ids: list[str]) -> None:
        """把已切分片段向量化后写入 Chroma。"""
        self.vector_store.add_documents(documents=documents, ids=ids)

    def delete_documents(self, ids: list[str]) -> None:
        """按片段 ID 删除向量，可用于文档删除或失败回滚。"""
        if ids:
            self.vector_store.delete(ids=ids)

    def snapshot_documents(self, ids: list[str]) -> dict:
        """删除前读取原始向量，失败回滚时可直接恢复且不再次调用 Embedding。"""
        if not ids:
            return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
        return self.vector_store.get(
            ids=ids,
            include=["documents", "metadatas", "embeddings"],
        )

    def restore_documents(self, snapshot: dict) -> None:
        """用 Chroma 原始 upsert 恢复快照；embedding 已在快照中，不产生模型费用。"""
        ids = snapshot.get("ids") or []
        if not ids:
            return
        self.vector_store._collection.upsert(
            ids=ids,
            documents=snapshot.get("documents"),
            metadatas=snapshot.get("metadatas"),
            embeddings=snapshot.get("embeddings"),
        )

    def contains_ids(self, ids: list[str]) -> bool:
        """检查指定片段是否仍在 Chroma 中，主要用于删除结果验证。"""
        if not ids:
            return False
        result = self.vector_store.get(ids=ids, include=[])
        return bool(result.get("ids"))
