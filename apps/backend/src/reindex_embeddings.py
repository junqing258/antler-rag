"""Maintenance-window embedding rebuild, with a strictly read-only preflight."""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from core.config import Settings
from db import Database
from db.repository import now
from db.schema import validate_schema
from rag import RAGStore
from rag.graph_store import GraphStore
from rag.store import upload_path
from services.document_indexing import DocumentIndexingService, prepare_source


def read_catalog(settings: Settings) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Never create directories, migrate schema, configure WAL, or open Chroma."""
    if not settings.db_path.is_file():
        raise ValueError(
            "Database does not exist; initialize the service with a new data directory first"
        )
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        validate_schema(conn)
        targets = []
        for kb in conn.execute(
            "SELECT * FROM knowledge_bases WHERE status != 'deleted' ORDER BY id"
        ).fetchall():
            for document in conn.execute(
                "SELECT * FROM documents WHERE knowledge_base_id=? AND status IN ('ready','indexing','failed','pending') ORDER BY id",
                (kb["id"],),
            ).fetchall():
                targets.append((dict(kb), dict(document)))
        return targets


def preflight(
    settings: Settings, targets: list[tuple[dict, dict]]
) -> tuple[list[tuple[dict, dict, list]], list[str]]:
    prepared = []
    errors = []
    for kb, document in targets:
        source = upload_path(settings.uploads_dir, kb["id"], document["stored_filename"])
        try:
            drafts = prepare_source(kb, document, source)
            prepared.append((kb, document, drafts))
        except Exception as error:  # noqa: BLE001 -- report each maintenance failure and stop/compensate
            errors.append(f"{kb['id']}/{document['id']} ({document['filename']}): {error}")
    return prepared, errors


def rebuild(settings: Settings, database: Database, store: RAGStore) -> tuple[int, int]:
    """Preflight all targets, invalidate all affected states, then replace vectors."""
    targets = read_catalog(settings)
    prepared, errors = preflight(settings, targets)
    if errors:
        for error in errors:
            print(f"Preflight failed: {error}")
        return 0, len(errors)
    graph = GraphStore(database)
    service = DocumentIndexingService(database, store, graph, settings)
    # This must commit before deleting the collection. Interruptions leave unprocessed
    # documents indexing and their old graph facts unqueryable.
    with database.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for kb, document, _ in prepared:
                conn.execute(
                    "UPDATE documents SET status='indexing',updated_at=? WHERE knowledge_base_id=? AND id=?",
                    (now(), kb["id"], document["id"]),
                )
            conn.execute("UPDATE graph_document_states SET status='stale',updated_at=?", (now(),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    store.recreate_collection()
    indexed = failed = 0
    for kb, document, drafts in prepared:
        try:
            service.index_document(kb, document, drafts=drafts)
            indexed += 1
        except Exception as error:  # noqa: BLE001 -- report each maintenance failure and stop/compensate
            print(f"Rebuild failed: {document['id']}: {error}")
            failed += 1
    return indexed, failed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild vectors during a maintenance window with all writers stopped"
    )
    parser.add_argument("--data-dir", help="Override RAG_DATA_DIR")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Delete and rebuild the entire active collection after a backup",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only schema/source/configuration check; no embedding or Chroma",
    )
    args = parser.parse_args()
    settings = Settings(data_dir=args.data_dir) if args.data_dir else Settings()
    if not settings.embedding_model:
        parser.error("Set RAG_EMBEDDING_MODEL before rebuilding an external embedding index.")
    try:
        targets = read_catalog(settings)
        prepared, errors = preflight(settings, targets)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    if args.dry_run:
        for kb, document, drafts in prepared:
            print(
                f"{kb['name']}/{document['filename']}: strategy={kb['chunk_strategy']} chunks={len(drafts)}"
            )
        for error in errors:
            print(f"Preflight failed: {error}")
        print(
            f"Prepared {len(prepared)} documents; {sum(len(drafts) for _, _, drafts in prepared)} chunks; {len(errors)} failures."
        )
        if errors:
            parser.exit(1)
        return
    if errors:
        parser.exit(1, "\n".join(errors) + "\nPreflight failed; collection was preserved.\n")
    store = RAGStore(settings)
    try:
        # Revalidate in rebuild; no previous dry-run or preflight is authoritative.
        indexed, failed = rebuild(settings, Database(settings.db_path), store)
        print(f"Rebuilt {indexed} documents; {failed} documents failed.")
        if failed:
            parser.exit(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
