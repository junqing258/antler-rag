"""Explicitly rebuild the active embedding collection from the original uploads."""

from __future__ import annotations

import argparse

import httpx

from .config import Settings
from .db import Database
from .documents import UnsupportedDocument, extract_text
from .rag import RAGStore
from .rag.store import upload_path


def rebuild(settings: Settings, database: Database, store: RAGStore) -> tuple[int, int]:
    """Recreate the configured collection and index every ready document again."""
    indexed = failed = 0
    store.recreate_collection()
    for knowledge_base in database.knowledge_bases():
        for document in database.documents(knowledge_base["id"]):
            if document["status"] != "ready":
                continue
            source = upload_path(settings.uploads_dir, knowledge_base["id"], document["stored_filename"])
            if not source.exists():
                database.set_document_status(
                    knowledge_base["id"],
                    document["id"],
                    "failed",
                    error="Original upload is missing; cannot rebuild embedding index",
                )
                failed += 1
                continue
            try:
                database.set_document_status(knowledge_base["id"], document["id"], "indexing")
                chunks = store.index(
                    knowledge_base_id=knowledge_base["id"],
                    document_id=document["id"],
                    filename=document["filename"],
                    text=extract_text(document["filename"], source.read_bytes()),
                    chunk_size=knowledge_base["chunk_size"],
                    chunk_overlap=knowledge_base["chunk_overlap"],
                    digest=document["sha256"],
                )
                database.set_document_status(knowledge_base["id"], document["id"], "ready", chunks)
                indexed += 1
            except (httpx.HTTPError, UnsupportedDocument, ValueError, OSError):
                database.set_document_status(
                    knowledge_base["id"],
                    document["id"],
                    "failed",
                    error="Unable to rebuild embedding index",
                )
                failed += 1
    return indexed, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild vectors for the configured embedding model")
    parser.add_argument("--data-dir", help="Override RAG_DATA_DIR")
    parser.add_argument("--confirm", action="store_true", help="Delete and rebuild the active collection")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("This deletes the active embedding collection. Re-run with --confirm after a backup.")

    settings = Settings(data_dir=args.data_dir) if args.data_dir else Settings()
    if not settings.embedding_model:
        parser.error("Set RAG_EMBEDDING_MODEL before rebuilding an external embedding index.")
    database = Database(settings.db_path)
    database.migrate()
    indexed, failed = rebuild(settings, database, RAGStore(settings))
    print(f"Rebuilt {indexed} documents; {failed} documents failed.")


if __name__ == "__main__":
    main()
