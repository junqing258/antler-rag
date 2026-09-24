"""SQLite persistence boundary for graph provenance and lifecycle state."""

from __future__ import annotations

from uuid import uuid4

from db import Database
from db.repository import now


class GraphStore:
    def __init__(self, database: Database):
        self.database = database

    def mark_not_built(
        self, *, knowledge_base_id: str, document_id: str, source_sha256: str
    ) -> None:
        """Record an indexed document as eligible for an admin-only graph rebuild."""
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ready = conn.execute(
                    "SELECT 1 FROM documents WHERE id=? AND knowledge_base_id=? AND status='ready'",
                    (document_id, knowledge_base_id),
                ).fetchone()
                if not ready:
                    raise ValueError("Graph state can only be recorded for a ready document")
                conn.execute(
                    """INSERT INTO graph_document_states(
                        knowledge_base_id,document_id,build_id,source_sha256,status,
                        extractor_model,extractor_version,indexed_at,error_code,updated_at
                    ) VALUES(?,?,NULL,?,'not_built',NULL,NULL,NULL,NULL,?)
                    ON CONFLICT(knowledge_base_id,document_id) DO UPDATE SET
                        build_id=NULL,source_sha256=excluded.source_sha256,status='not_built',
                        extractor_model=NULL,extractor_version=NULL,indexed_at=NULL,
                        error_code=NULL,updated_at=excluded.updated_at""",
                    (knowledge_base_id, document_id, source_sha256, now()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def document_states(self, knowledge_base_id: str) -> list[dict[str, object]]:
        return self.database.many(
            """SELECT document_id,build_id,source_sha256,status,extractor_model,extractor_version,
                      indexed_at,error_code,updated_at
               FROM graph_document_states WHERE knowledge_base_id=? ORDER BY updated_at DESC""",
            (knowledge_base_id,),
        )

    def search(self, *, knowledge_base_id: str, query: str, top_k: int) -> list[dict[str, object]]:
        terms = [term.casefold() for term in query.split() if len(term) > 1][:5]
        if not terms:
            return []
        where = " OR ".join("e.normalized_name LIKE ?" for _ in terms)
        rows = self.database.many(
            f"""SELECT rm.document_id,rm.chunk_id,e.canonical_name AS subject,r.predicate,
                       target.canonical_name AS object,r.confidence
                FROM entities e JOIN relations r ON r.subject_entity_id=e.id
                JOIN entities target ON target.id=r.object_entity_id
                JOIN relation_mentions rm ON rm.relation_id=r.id
                JOIN graph_document_states state ON state.knowledge_base_id=rm.knowledge_base_id
                   AND state.document_id=rm.document_id AND state.status='ready'
                WHERE e.knowledge_base_id=? AND r.knowledge_base_id=? AND ({where})
                ORDER BY r.confidence DESC, rm.chunk_id LIMIT ?""",
            (knowledge_base_id, knowledge_base_id, *[f"%{term}%" for term in terms], top_k),
        )
        return rows

    def start_build(
        self, *, knowledge_base_id: str, requested_by: str | None, extractor_model: str, extractor_version: str
    ) -> str:
        build_id, stamp = str(uuid4()), now()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO graph_builds(id,knowledge_base_id,requested_by,status,extractor_model,
                       extractor_version,schema_version,requested_at,started_at)
                       VALUES(?,?,?,'running',?,?,1,?,?)""",
                    (build_id, knowledge_base_id, requested_by, extractor_model, extractor_version, stamp, stamp),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return build_id

    def finish_build(self, *, build_id: str, status: str, error_code: str | None = None) -> None:
        if status not in {"ready", "failed"}:
            raise ValueError("Invalid graph build terminal status")
        self.database.run(
            "UPDATE graph_builds SET status=?,finished_at=?,error_code=? WHERE id=? AND status='running'",
            (status, now(), error_code, build_id),
        )

    def mark_failed(
        self, *, knowledge_base_id: str, document_id: str, build_id: str, source_sha256: str, error_code: str
    ) -> None:
        self._set_state(
            knowledge_base_id=knowledge_base_id, document_id=document_id, build_id=build_id,
            source_sha256=source_sha256, status="failed", error_code=error_code,
        )

    def mark_ready(
        self, *, knowledge_base_id: str, document_id: str, build_id: str, source_sha256: str,
        extractor_model: str, extractor_version: str,
    ) -> None:
        self._set_state(
            knowledge_base_id=knowledge_base_id, document_id=document_id, build_id=build_id,
            source_sha256=source_sha256, status="ready", error_code=None,
            extractor_model=extractor_model, extractor_version=extractor_version,
        )

    def replace_document_facts(
        self, *, knowledge_base_id: str, document_id: str, build_id: str, source_sha256: str,
        extractor_model: str, extractor_version: str, facts: list[dict[str, object]],
    ) -> None:
        """Atomically replace one document's provenance with validated extractor facts."""
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                document = conn.execute(
                    "SELECT status,sha256 FROM documents WHERE id=? AND knowledge_base_id=?",
                    (document_id, knowledge_base_id),
                ).fetchone()
                if not document or document["status"] != "ready" or document["sha256"] != source_sha256:
                    raise ValueError("Document changed while graph build was running")
                self._cleanup_provenance(conn, knowledge_base_id, document_id, remove_state=False)
                entity_ids: dict[tuple[str, str], str] = {}
                for fact in facts:
                    chunk_id = str(fact["chunk_id"])
                    for entity in fact["entities"]:  # type: ignore[union-attr]
                        name, entity_type = str(entity["name"]), str(entity["type"])
                        normalized = name.casefold().strip()
                        row = conn.execute(
                            "SELECT id FROM entities WHERE knowledge_base_id=? AND normalized_name=? AND entity_type=?",
                            (knowledge_base_id, normalized, entity_type),
                        ).fetchone()
                        entity_id = str(row["id"]) if row else str(uuid4())
                        if not row:
                            conn.execute(
                                "INSERT INTO entities VALUES(?,?,?,?,?,?,?)",
                                (entity_id, knowledge_base_id, name, normalized, entity_type, now(), now()),
                            )
                        entity_ids[(normalized, entity_type)] = entity_id
                        conn.execute(
                            "INSERT OR IGNORE INTO entity_mentions VALUES(?,?,?,?,?,?,?)",
                            (str(uuid4()), entity_id, knowledge_base_id, document_id, chunk_id, 0, len(name)),
                        )
                    for relation in fact["relations"]:  # type: ignore[union-attr]
                        subject = entity_ids.get((str(relation["subject"]).casefold().strip(), str(relation["subject_type"])))
                        object_ = entity_ids.get((str(relation["object"]).casefold().strip(), str(relation["object_type"])))
                        if not subject or not object_:
                            continue
                        predicate, confidence = str(relation["predicate"]), float(relation["confidence"])
                        row = conn.execute(
                            """SELECT id FROM relations WHERE knowledge_base_id=? AND subject_entity_id=?
                               AND predicate=? AND object_entity_id=?""",
                            (knowledge_base_id, subject, predicate, object_),
                        ).fetchone()
                        relation_id = str(row["id"]) if row else str(uuid4())
                        if not row:
                            conn.execute(
                                "INSERT INTO relations VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (relation_id, knowledge_base_id, subject, predicate, object_, confidence,
                                 extractor_model, extractor_version, now(), now()),
                            )
                        conn.execute(
                            "INSERT OR IGNORE INTO relation_mentions VALUES(?,?,?,?,?,?)",
                            (str(uuid4()), relation_id, knowledge_base_id, document_id, chunk_id, build_id),
                        )
                conn.execute(
                    """INSERT INTO graph_document_states VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(knowledge_base_id,document_id) DO UPDATE SET build_id=excluded.build_id,
                       source_sha256=excluded.source_sha256,status='ready',extractor_model=excluded.extractor_model,
                       extractor_version=excluded.extractor_version,indexed_at=excluded.indexed_at,
                       error_code=NULL,updated_at=excluded.updated_at""",
                    (knowledge_base_id, document_id, build_id, source_sha256, "ready", extractor_model,
                     extractor_version, now(), None, now()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _cleanup_provenance(conn: object, knowledge_base_id: str, document_id: str, *, remove_state: bool) -> None:
        # sqlite.Connection deliberately stays structural here to keep the transaction private.
        conn.execute("DELETE FROM relation_mentions WHERE knowledge_base_id=? AND document_id=?", (knowledge_base_id, document_id))  # type: ignore[union-attr]
        conn.execute("DELETE FROM entity_mentions WHERE knowledge_base_id=? AND document_id=?", (knowledge_base_id, document_id))  # type: ignore[union-attr]
        if remove_state:
            conn.execute("DELETE FROM graph_document_states WHERE knowledge_base_id=? AND document_id=?", (knowledge_base_id, document_id))  # type: ignore[union-attr]
        conn.execute("DELETE FROM relations WHERE knowledge_base_id=? AND NOT EXISTS (SELECT 1 FROM relation_mentions rm WHERE rm.relation_id=relations.id)", (knowledge_base_id,))  # type: ignore[union-attr]
        conn.execute("DELETE FROM entity_aliases WHERE entity_id IN (SELECT e.id FROM entities e WHERE e.knowledge_base_id=? AND NOT EXISTS (SELECT 1 FROM entity_mentions em WHERE em.entity_id=e.id) AND NOT EXISTS (SELECT 1 FROM relations r WHERE r.subject_entity_id=e.id OR r.object_entity_id=e.id))", (knowledge_base_id,))  # type: ignore[union-attr]
        conn.execute("DELETE FROM entities WHERE knowledge_base_id=? AND NOT EXISTS (SELECT 1 FROM entity_mentions em WHERE em.entity_id=entities.id) AND NOT EXISTS (SELECT 1 FROM relations r WHERE r.subject_entity_id=entities.id OR r.object_entity_id=entities.id)", (knowledge_base_id,))  # type: ignore[union-attr]

    def _set_state(self, *, knowledge_base_id: str, document_id: str, build_id: str, source_sha256: str,
                   status: str, error_code: str | None, extractor_model: str | None = None,
                   extractor_version: str | None = None) -> None:
        self.database.run(
            """INSERT INTO graph_document_states(knowledge_base_id,document_id,build_id,source_sha256,status,
               extractor_model,extractor_version,indexed_at,error_code,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(knowledge_base_id,document_id) DO UPDATE SET build_id=excluded.build_id,
               source_sha256=excluded.source_sha256,status=excluded.status,extractor_model=excluded.extractor_model,
               extractor_version=excluded.extractor_version,indexed_at=excluded.indexed_at,
               error_code=excluded.error_code,updated_at=excluded.updated_at""",
            (knowledge_base_id, document_id, build_id, source_sha256, status, extractor_model,
             extractor_version, now() if status == "ready" else None, error_code, now()),
        )

    def cleanup_document(self, *, knowledge_base_id: str, document_id: str) -> None:
        """Remove one document's provenance, then only facts with no provenance."""
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._cleanup_provenance(conn, knowledge_base_id, document_id, remove_state=True)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
