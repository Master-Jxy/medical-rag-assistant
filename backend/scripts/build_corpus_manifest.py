"""从本机 MySQL、文件和 Chroma 只读生成或核验 corpus_v1。"""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import chromadb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_engine
from app.evaluation.corpus import SourceChunk, SourceDocument, build_corpus_manifest
from app.modules.knowledge.models import KnowledgeDocument

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "evaluation" / "corpora" / "corpus_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="只比对现有清单，不写文件")
    return parser.parse_args()


def build_current_manifest(generated_on: str):
    settings = get_settings()
    with Session(get_engine()) as session:
        records = list(
            session.scalars(
                select(KnowledgeDocument).order_by(
                    KnowledgeDocument.original_name, KnowledgeDocument.id
                )
            )
        )
    source_documents = []
    for record in records:
        path = settings.upload_dir / record.stored_name
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        source_documents.append(
            SourceDocument(
                document_id=record.id,
                original_name=record.original_name,
                stored_name=record.stored_name,
                registered_content_sha256=record.content_hash,
                actual_content_sha256=actual_hash,
                size_bytes=record.size_bytes,
                actual_size_bytes=path.stat().st_size if path.is_file() else None,
                chunk_ids=tuple(record.chunk_ids),
            )
        )
    collection = chromadb.PersistentClient(path=str(settings.chroma_persist_dir)).get_collection(
        settings.chroma_collection_name
    )
    snapshot = collection.get(include=["documents", "metadatas"])
    source_chunks = [
        SourceChunk(chunk_id=chunk_id, content=content or "", metadata=metadata or {})
        for chunk_id, content, metadata in zip(
            snapshot.get("ids") or [],
            snapshot.get("documents") or [],
            snapshot.get("metadatas") or [],
            strict=True,
        )
    ]
    return build_corpus_manifest(
        documents=source_documents,
        chunks=source_chunks,
        generated_on=generated_on,
        chroma_collection=settings.chroma_collection_name,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


def main() -> None:
    args = parse_args()
    generated_on = date.today().isoformat()
    if args.check and args.output.is_file():
        generated_on = json.loads(args.output.read_text(encoding="utf-8"))["generated_on"]
    manifest = build_current_manifest(generated_on)
    rendered = json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        existing = args.output.read_text(encoding="utf-8")
        if existing != rendered:
            raise SystemExit("corpus_v1 与当前本机语料不一致")
        print(
            f"corpus_v1 OK: documents={manifest.document_count}, "
            f"chunks={manifest.chunk_count}, status={manifest.audit_result.status}"
        )
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"written={args.output}")
    print(
        f"documents={manifest.document_count}, chunks={manifest.chunk_count}, "
        f"status={manifest.audit_result.status}"
    )


if __name__ == "__main__":
    main()
