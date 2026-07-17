"""批量导入走系统文档生命周期，并按内容哈希保持幂等。"""

import asyncio

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine
from app.services.admin_document_service import AdminDocumentService
from scripts.import_documents import import_directory
from tests.test_document_service import FakeVectorStore


def test_batch_import_is_idempotent_and_creates_system_documents(tmp_path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "一.txt").write_text("第一份医学资料", encoding="utf-8")
    (source_dir / "二.txt").write_text("第二份医学资料", encoding="utf-8")

    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    vector_store = FakeVectorStore()
    service = AdminDocumentService(
        session,
        settings=Settings(
            _env_file=None,
            upload_dir=tmp_path / "uploads",
            document_registry_path=tmp_path / "documents.json",
            chunk_size=30,
            chunk_overlap=5,
        ),
        vector_store=vector_store,
    )
    try:
        assert asyncio.run(import_directory(source_dir, service)) == 0
        first_vector_ids = list(vector_store.added_ids)
        assert service.repository.count() == 2
        assert all(record.is_system for record in service.repository.list_all())

        assert asyncio.run(import_directory(source_dir, service)) == 0
        assert service.repository.count() == 2
        assert vector_store.added_ids == first_vector_ids
    finally:
        session.close()
        engine.dispose()
