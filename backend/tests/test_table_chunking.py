from types import SimpleNamespace

from langchain_core.documents import Document

from app.modules.knowledge.lifecycle import DocumentLifecycleService


def service_with_chunk_size(chunk_size: int) -> DocumentLifecycleService:
    service = object.__new__(DocumentLifecycleService)
    service.settings = SimpleNamespace(chunk_size=chunk_size)
    return service


def test_table_chunking_never_exceeds_limit_for_long_header_and_row() -> None:
    service = service_with_chunk_size(20)
    document = Document(
        page_content=f"{'H' * 45}\n{'R' * 55}\nshort",
        metadata={"element_kind": "table", "document_id": "doc"},
    )

    chunks = service._split_table_document(document)

    assert chunks
    assert all(0 < len(chunk.page_content) <= 20 for chunk in chunks)
    assert "".join(chunk.page_content for chunk in chunks[:3]) == "H" * 45
    assert all(chunk.metadata["document_id"] == "doc" for chunk in chunks)


def test_table_chunking_repeats_normal_header_for_oversized_rows() -> None:
    service = service_with_chunk_size(20)
    document = Document(
        page_content=f"name | value\n{'x' * 30}",
        metadata={"element_kind": "table"},
    )

    chunks = service._split_table_document(document)

    assert len(chunks) > 1
    assert all(chunk.page_content.startswith("name | value\n") for chunk in chunks)
    assert all(len(chunk.page_content) <= 20 for chunk in chunks)
