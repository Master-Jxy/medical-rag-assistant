"""把旧 documents.json 登记导入 MySQL；不读取正文，也不改写 Chroma。"""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.modules.knowledge.models import KnowledgeDocument
from app.modules.knowledge.repository import DocumentRepository


def import_legacy_registry(session: Session, registry_path: Path) -> int:
    records = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("documents.json 顶层必须是数组")

    repository = DocumentRepository(session)
    imported = 0
    for record in records:
        chunk_ids = record["chunk_ids"]
        if not isinstance(chunk_ids, list) or len(chunk_ids) != record["chunk_count"]:
            raise ValueError(f"文档 {record.get('document_id')} 的片段登记不一致")

        existing = repository.get_by_id(record["document_id"])
        if existing is not None:
            if existing.content_hash != record["file_hash"] or not existing.is_system:
                raise ValueError(f"文档 {record['document_id']} 与已有数据库记录冲突")
            continue

        repository.add(
            KnowledgeDocument(
                id=record["document_id"],
                original_name=record["file_name"],
                stored_name=record["stored_name"],
                content_hash=record["file_hash"],
                size_bytes=record["file_size"],
                chunk_count=record["chunk_count"],
                chunk_ids=chunk_ids,
                uploader_id=None,
                is_system=True,
                status=record.get("status", "ready"),
                created_at=datetime.fromisoformat(record["created_at"]),
            )
        )
        imported += 1

    session.commit()
    return imported
