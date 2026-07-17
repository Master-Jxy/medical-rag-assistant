"""通过系统文档生命周期批量导入本地 PDF/TXT，按内容哈希幂等跳过。"""

import argparse
import asyncio
import sys
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.exceptions import DuplicateDocumentError  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.services.admin_document_service import AdminDocumentService  # noqa: E402


async def import_directory(directory: Path, service: AdminDocumentService) -> int:
    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".txt"}
    )
    if not files:
        print(f"No PDF or TXT files found in: {directory}")
        return 1

    imported = 0
    skipped = 0
    failed = 0
    for path in files:
        try:
            upload = UploadFile(filename=path.name, file=path.open("rb"))
            result = await service.create_system_document(upload)
            imported += 1
            print(f"[IMPORTED] {path.name} ({result.chunk_count} chunks)")
        except DuplicateDocumentError:
            skipped += 1
            print(f"[SKIPPED]  {path.name} (duplicate content)")
        except Exception as exc:
            failed += 1
            print(f"[FAILED]   {path.name}: {exc}")

    print(f"Done: imported={imported}, skipped={skipped}, failed={failed}")
    return 1 if failed else 0


async def run_import(directory: Path) -> int:
    with Session(get_engine()) as session:
        return await import_directory(directory, AdminDocumentService(session))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a folder as system documents into the RAG knowledge base"
    )
    parser.add_argument("directory", type=Path, help="Directory containing PDF/TXT files")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认产生 Embedding 费用并写入正式知识库",
    )
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        parser.error(f"Directory does not exist: {directory}")
    if not args.confirm:
        parser.error("未提供 --confirm，不会调用 Embedding 或写入知识库")
    return asyncio.run(run_import(directory))


if __name__ == "__main__":
    raise SystemExit(main())
