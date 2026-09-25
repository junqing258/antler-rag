"""One-time storage migration helpers for schema version 2."""

from __future__ import annotations

import shutil

from core.config import Settings
from db import Database
from rag import RAGStore
from rag.store import upload_path
from utils.documents import UnsupportedDocument, extract_text


def stage_legacy_uploads(settings: Settings, database: Database) -> bool:
    """Copy v1 tenant uploads before the schema conversion drops tenant IDs."""
    if database.schema_version() != 1:
        return False
    with database.connection() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tenants'").fetchone():
            return False
        documents = conn.execute("SELECT tenant_id,knowledge_base_id,stored_filename FROM documents").fetchall()
    for document in documents:
        source = settings.data_dir / "tenants" / document["tenant_id"] / "knowledge-bases" / document["knowledge_base_id"] / "uploads" / document["stored_filename"]
        destination = upload_path(settings.uploads_dir, document["knowledge_base_id"], document["stored_filename"])
        if source.exists() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return True


def rebuild_chroma(settings: Settings, database: Database, store: RAGStore) -> None:
    """Replace tenant-tagged Chroma records with global-workspace metadata."""
    store.recreate_collection()
    for knowledge_base in database.knowledge_bases():
        for document in database.documents(knowledge_base["id"]):
            if document["status"] != "ready":
                continue
            source = upload_path(settings.uploads_dir, knowledge_base["id"], document["stored_filename"])
            if not source.exists():
                database.set_document_status(knowledge_base["id"], document["id"], "failed", error="Original upload is missing after migration")
                continue
            try:
                chunks = store.index(knowledge_base_id=knowledge_base["id"], document_id=document["id"], filename=document["filename"], text=extract_text(document["filename"], source.read_bytes()), chunk_size=knowledge_base["chunk_size"], chunk_overlap=knowledge_base["chunk_overlap"], digest=document["sha256"])
                database.set_document_status(knowledge_base["id"], document["id"], "ready", chunks)
            except (UnsupportedDocument, ValueError):
                database.set_document_status(knowledge_base["id"], document["id"], "failed", error="Unable to rebuild index after migration")
