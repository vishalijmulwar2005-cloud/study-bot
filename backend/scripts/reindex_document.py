"""Re-index READY documents with the current processing pipeline.

Use after changing extraction/chunking/embedding logic: existing documents
keep their old chunks until re-processed, and the retry endpoint only accepts
FAILED documents. This script re-runs the same pipeline as the worker
(extract -> chunk -> embed -> replace chunks transactionally) in-place.

Usage:
    python scripts/reindex_document.py                 # all READY documents
    python scripts/reindex_document.py <doc-uuid> ...  # specific documents

Run from the backend/ directory (uses the same .env and Settings as the app).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text as sql_text

from app.bundle import build_bundle
from app.config import get_settings
from app.database import get_engine
from app.services.pdf_processor import PageText


def _ready_documents(engine, doc_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, str]]:
    with engine.connect() as conn:
        if doc_ids:
            rows = conn.execute(
                sql_text(
                    "SELECT id, storage_key FROM documents "
                    "WHERE status = 'READY' AND id = ANY(:ids)"
                ),
                {"ids": doc_ids},
            ).fetchall()
        else:
            rows = conn.execute(
                sql_text(
                    "SELECT id, storage_key FROM documents WHERE status = 'READY'"
                )
            ).fetchall()
    return [(row.id, row.storage_key) for row in rows]


async def _reindex_one(bundle, engine, document_id: uuid.UUID, storage_key: str) -> int:
    """Same pipeline as worker._process_job, minus job bookkeeping."""
    data = bundle.storage.load(storage_key)
    pages: list[PageText] = bundle.processor.extract_pages(data)
    chunks = bundle.chunker.chunk_pages(pages)
    if not chunks:
        raise RuntimeError("chunker produced no chunks")

    embeddings = await bundle.embeddings.embed_texts([c.text for c in chunks])
    rows = [
        {
            "id": uuid.uuid4(),
            "chunk_index": chunk.chunk_index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "section": chunk.section,
            "text": chunk.text,
            "token_count": chunk.token_count,
        }
        for chunk in chunks
    ]

    # Atomic replace, exactly like the worker: chunks never exist without a
    # READY document.
    with engine.begin() as conn:
        inserted = bundle.store.replace_document_chunks(conn, document_id, rows, embeddings)
        conn.execute(
            sql_text("UPDATE documents SET updated_at = now() WHERE id = :id"),
            {"id": document_id},
        )
    return inserted


async def main() -> int:
    doc_ids = [uuid.UUID(arg) for arg in sys.argv[1:]]
    settings = get_settings()
    bundle = build_bundle(settings)
    engine = get_engine(settings)

    docs = _ready_documents(engine, doc_ids)
    if doc_ids and not docs:
        print("No READY documents matched the given ids.")
        return 1
    print(f"Re-indexing {len(docs)} document(s) with dim={settings.embedding_dim} ...")
    failures = 0
    for document_id, storage_key in docs:
        try:
            inserted = await _reindex_one(bundle, engine, document_id, storage_key)
            print(f"  OK  {document_id}  chunks={inserted}")
        except Exception as exc:  # noqa: BLE001 — report every document
            failures += 1
            print(f"  ERR {document_id}  {exc.__class__.__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
