"""一次性把旧 JSON 文档登记迁移到 MySQL，已有向量不会重新生成。"""

import json
from pathlib import Path

import chromadb
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.modules.knowledge.migration import import_legacy_registry
from app.modules.knowledge.repository import DocumentRepository


def main() -> None:
    settings = get_settings()
    registry_path = Path(settings.document_registry_path)
    records = json.loads(registry_path.read_text(encoding="utf-8"))

    missing_files = [
        record["document_id"]
        for record in records
        if not (settings.upload_dir / record["stored_name"]).is_file()
    ]
    if missing_files:
        raise RuntimeError(f"有 {len(missing_files)} 份登记缺少原文件，停止迁移")

    registered_chunk_ids = {
        chunk_id for record in records for chunk_id in record["chunk_ids"]
    }
    collection = chromadb.PersistentClient(
        path=str(settings.chroma_persist_dir)
    ).get_collection(settings.chroma_collection_name)
    chroma_chunk_ids = set(collection.get(include=[])["ids"])
    if registered_chunk_ids != chroma_chunk_ids:
        raise RuntimeError("documents.json 与 Chroma 片段 ID 不一致，停止迁移")

    with Session(get_engine()) as session:
        imported = import_legacy_registry(session, registry_path)
        total = DocumentRepository(session).count()

    print(f"imported={imported}")
    print(f"documents_total={total}")
    print(f"chroma_chunks={len(chroma_chunk_ids)}")


if __name__ == "__main__":
    main()
