"""HTTP 上传与维护重建共用的文档替换生命周期。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from loguru import logger

from core.config import Settings
from db import Database
from rag.chunking import ChunkDraft, chunk_recursive, chunk_structure
from rag.contracts import IndexStore
from rag.graph_store import GraphStore
from rag.store import upload_path
from utils.documents import extract_text, parse_document


def prepare_drafts(
    knowledge_base: dict[str, Any], filename: str, content: bytes
) -> list[ChunkDraft]:
    """在任何破坏性操作之前完成校验与全部准备工作。"""
    size, overlap = knowledge_base["chunk_size"], knowledge_base["chunk_overlap"]
    if not 100 <= size <= 4000 or not 0 <= overlap <= 1000 or overlap >= size:
        raise ValueError("Invalid knowledge base chunk size/overlap configuration")
    strategy = knowledge_base["chunk_strategy"]
    if strategy == "recursive":
        return chunk_recursive(
            extract_text(filename, content), chunk_size=size, chunk_overlap=overlap
        )
    if strategy == "structure":
        return chunk_structure(
            parse_document(filename, content), chunk_size=size, chunk_overlap=overlap
        )
    raise ValueError(f"Unsupported chunk strategy: {strategy}")


def prepare_source(
    knowledge_base: dict[str, Any], document: dict[str, Any], source: Path
) -> list[ChunkDraft]:
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != document["sha256"]:
        raise ValueError("Original upload SHA256 does not match the document record")
    return prepare_drafts(knowledge_base, document["filename"], content)


class DocumentIndexingService:
    def __init__(
        self, database: Database, store: IndexStore, graph: GraphStore, settings: Settings
    ):
        self.database, self.store, self.graph, self.settings = database, store, graph, settings

    def upload(
        self, knowledge_base: dict[str, Any], *, filename: str, content: bytes, created_by: str
    ) -> dict[str, Any]:
        kb_id = knowledge_base["id"]
        digest = hashlib.sha256(content).hexdigest()
        snapshot = self.database.one(
            "SELECT * FROM documents WHERE knowledge_base_id=? AND sha256=?",
            (kb_id, digest),
        )
        stored = f"{uuid4()}{Path(filename).suffix.lower()}"
        document = self.database.create_document(
            kb_id, filename, stored, digest, len(content), created_by
        )
        source = upload_path(self.settings.uploads_dir, kb_id, stored)
        created_source = False
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            # 独占创建可防止覆盖/误删无关的已有源文件。
            with source.open("xb") as handle:
                created_source = True
                handle.write(content)
            drafts = prepare_drafts(knowledge_base, filename, content)
        except Exception as error:
            self._fail(
                knowledge_base,
                document,
                error,
                operation="upload",
                source=source,
                created_source_in_this_attempt=created_source,
                snapshot=snapshot,
                replacement_started=False,
            )
            raise
        self.index_document(
            knowledge_base,
            document,
            drafts=drafts,
            operation="upload",
            created_source_in_this_attempt=created_source,
            snapshot=snapshot,
        )
        # 索引已提交，此时才能移除旧的、不再被引用的源文件。
        if snapshot and snapshot["stored_filename"] != stored:
            old_source = upload_path(self.settings.uploads_dir, kb_id, snapshot["stored_filename"])
            referenced = self.database.one(
                "SELECT id FROM documents WHERE knowledge_base_id=? AND stored_filename=? AND status != 'deleted'",
                (kb_id, snapshot["stored_filename"]),
            )
            if not referenced:
                try:
                    old_source.unlink(missing_ok=True)
                except OSError as error:
                    message = (
                        f"Indexing succeeded; old source cleanup failed ({old_source}): {error}"
                    )
                    self.database.run(
                        "UPDATE documents SET error_message=? WHERE knowledge_base_id=? AND id=?",
                        (message, kb_id, document["id"]),
                    )
                    logger.warning(message)
        return self.database.document(kb_id, document["id"]) or {}

    def index_document(
        self,
        knowledge_base: dict[str, Any],
        document: dict[str, Any],
        *,
        drafts: list[ChunkDraft] | None = None,
        operation: Literal["upload", "rebuild"] = "rebuild",
        created_source_in_this_attempt: bool = False,
        snapshot: dict[str, Any] | None = None,
    ) -> int:
        kb_id, doc_id = knowledge_base["id"], document["id"]
        source = upload_path(self.settings.uploads_dir, kb_id, document["stored_filename"])
        # 重建预检失败时，旧索引与生命周期状态保持不变。
        if drafts is None:
            drafts = prepare_source(knowledge_base, document, source)
        try:
            self.database.set_document_status(kb_id, doc_id, "indexing")
            self.database.run(
                "UPDATE graph_document_states SET status='stale' WHERE knowledge_base_id=? AND document_id=?",
                (kb_id, doc_id),
            )
            self.graph.cleanup_document(knowledge_base_id=kb_id, document_id=doc_id)
            self.store.delete_document(kb_id, doc_id)
            strategy = knowledge_base["chunk_strategy"]
            count = self.store.index_drafts(
                knowledge_base_id=kb_id,
                document_id=doc_id,
                filename=document["filename"],
                drafts=drafts,
                digest=document["sha256"],
                chunk_strategy=strategy,
            )
            with self.database.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    self.database.set_document_ready_in_tx(
                        conn,
                        knowledge_base_id=kb_id,
                        document_id=doc_id,
                        chunk_count=count,
                        expected_sha256=document["sha256"],
                    )
                    self.graph.mark_not_built_in_tx(
                        conn,
                        knowledge_base_id=kb_id,
                        document_id=doc_id,
                        source_sha256=document["sha256"],
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            return count
        except Exception as error:
            self._fail(
                knowledge_base,
                document,
                error,
                operation=operation,
                source=source,
                created_source_in_this_attempt=created_source_in_this_attempt,
                snapshot=snapshot,
                replacement_started=True,
            )
            raise

    def _fail(
        self,
        knowledge_base: dict[str, Any],
        document: dict[str, Any],
        error: Exception,
        *,
        operation: Literal["upload", "rebuild"],
        source: Path,
        created_source_in_this_attempt: bool,
        snapshot: dict[str, Any] | None,
        replacement_started: bool,
    ) -> None:
        kb_id, doc_id = knowledge_base["id"], document["id"]
        cleanup_errors: list[str] = []
        if replacement_started:
            for label, cleanup in (
                (
                    "graph",
                    lambda: self.graph.cleanup_document(
                        knowledge_base_id=kb_id, document_id=doc_id
                    ),
                ),
                ("vectors", lambda: self.store.delete_document(kb_id, doc_id)),
            ):
                try:
                    cleanup()
                except Exception as cleanup_error:  # noqa: BLE001 -- preserve the original failure and record compensation failures
                    cleanup_errors.append(
                        f"{label} cleanup failed (retry required): {cleanup_error}"
                    )
        restored = False
        if snapshot:
            old_source = upload_path(self.settings.uploads_dir, kb_id, snapshot["stored_filename"])
            if old_source.exists():
                try:
                    self.database.restore_document_source(kb_id, doc_id, snapshot)
                    restored = True
                except Exception as cleanup_error:  # noqa: BLE001 -- preserve the original failure and record compensation failures
                    cleanup_errors.append(f"source reference restoration failed: {cleanup_error}")
        # 若恢复在用的旧源文件失败，则两个文件都保留，交给维护处理。
        if (
            operation == "upload"
            and created_source_in_this_attempt
            and (not snapshot or restored or not old_source.exists())
        ):
            try:
                source.unlink(missing_ok=True)
            except OSError as cleanup_error:
                cleanup_errors.append(f"source cleanup failed (retry required): {cleanup_error}")
        message = str(error) + ("; " + "; ".join(cleanup_errors) if cleanup_errors else "")
        self.database.set_document_status(kb_id, doc_id, "failed", 0, error=message)
        if cleanup_errors:
            logger.error(
                "document_index_cleanup_failed document_id={} errors={}", doc_id, cleanup_errors
            )
            error.add_note("; ".join(cleanup_errors))
