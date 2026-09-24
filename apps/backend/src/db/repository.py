from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_SCHEMA_VERSION = 3


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """SQLite repository for a single global knowledge workspace."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    def schema_version(self) -> int:
        if not self.path.exists():
            return 0
        with self.connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone():
                return 0
            return int(
                conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            )

    def migrate(self) -> list[int]:
        applied: list[int] = []
        version = self.schema_version()
        if version > MAX_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {version} is newer than this service supports ({MAX_SCHEMA_VERSION})"
            )
        if version == 0:
            initial = Path(__file__).parent / "migrations" / "001_initial.sql"
            with self.connection() as conn:
                conn.executescript(initial.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)", (now(),)
                )
            applied.append(1)
            version = 1
        if version < 2:
            self._migrate_v2()
            applied.append(2)
            version = 2
        if version < 3:
            self._migrate_v3()
            applied.append(3)
        return applied

    @staticmethod
    def _v3_statements() -> tuple[str, ...]:
        """One statement per execute: executescript would commit this transaction."""
        return (
            """CREATE TABLE graph_builds (
                id TEXT PRIMARY KEY,
                knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                requested_by TEXT REFERENCES users(id),
                status TEXT NOT NULL CHECK(status IN ('queued','running','ready','failed')),
                extractor_model TEXT NOT NULL, extractor_version TEXT NOT NULL,
                schema_version INTEGER NOT NULL, requested_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, error_code TEXT
            )""",
            """CREATE TABLE graph_document_states (
                knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                document_id TEXT NOT NULL REFERENCES documents(id),
                build_id TEXT REFERENCES graph_builds(id), source_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('not_built','building','ready','stale','failed')),
                extractor_model TEXT, extractor_version TEXT, indexed_at TEXT,
                error_code TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY(knowledge_base_id, document_id)
            )""",
            """CREATE TABLE entities (
                id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL, entity_type TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(knowledge_base_id, normalized_name, entity_type), UNIQUE(knowledge_base_id, id)
            )""",
            """CREATE TABLE entity_aliases (
                id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id), normalized_alias TEXT NOT NULL,
                UNIQUE(entity_id, normalized_alias)
            )""",
            """CREATE TABLE relations (
                id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id),
                subject_entity_id TEXT NOT NULL, predicate TEXT NOT NULL, object_entity_id TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                extractor_model TEXT NOT NULL, extractor_version TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(knowledge_base_id, subject_entity_id, predicate, object_entity_id),
                UNIQUE(knowledge_base_id, id),
                FOREIGN KEY(knowledge_base_id, subject_entity_id) REFERENCES entities(knowledge_base_id, id),
                FOREIGN KEY(knowledge_base_id, object_entity_id) REFERENCES entities(knowledge_base_id, id)
            )""",
            """CREATE TABLE entity_mentions (
                id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, knowledge_base_id TEXT NOT NULL,
                document_id TEXT NOT NULL REFERENCES documents(id), chunk_id TEXT NOT NULL,
                start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                UNIQUE(entity_id, chunk_id, start_offset, end_offset),
                FOREIGN KEY(knowledge_base_id, entity_id) REFERENCES entities(knowledge_base_id, id)
            )""",
            """CREATE TABLE relation_mentions (
                id TEXT PRIMARY KEY, relation_id TEXT NOT NULL, knowledge_base_id TEXT NOT NULL,
                document_id TEXT NOT NULL REFERENCES documents(id), chunk_id TEXT NOT NULL,
                build_id TEXT NOT NULL REFERENCES graph_builds(id),
                UNIQUE(relation_id, chunk_id, build_id),
                FOREIGN KEY(knowledge_base_id, relation_id) REFERENCES relations(knowledge_base_id, id)
            )""",
            "CREATE INDEX graph_builds_kb_idx ON graph_builds(knowledge_base_id, status, requested_at DESC)",
            "CREATE INDEX graph_document_states_kb_idx ON graph_document_states(knowledge_base_id, status, updated_at DESC)",
            "CREATE INDEX entities_kb_name_idx ON entities(knowledge_base_id, normalized_name, entity_type)",
            "CREATE INDEX relations_kb_subject_idx ON relations(knowledge_base_id, subject_entity_id, predicate)",
            "CREATE INDEX relations_kb_object_idx ON relations(knowledge_base_id, object_entity_id, predicate)",
            "CREATE INDEX entity_mentions_kb_document_idx ON entity_mentions(knowledge_base_id, document_id, chunk_id)",
            "CREATE INDEX relation_mentions_kb_document_idx ON relation_mentions(knowledge_base_id, document_id, chunk_id)",
        )

    def _migrate_v3(self) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in self._v3_statements():
                    conn.execute(statement)
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"foreign key check failed: {violations!r}")
                conn.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(3,?)", (now(),)
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _migrate_v2(self) -> None:
        """Convert the historical tenant schema. FK mode must change before BEGIN."""
        with self.connection() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.execute("BEGIN IMMEDIATE")
                stamp = now()
                conn.executescript(
                    """
                    CREATE TABLE users_v2 (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE COLLATE NOCASE,password_hash TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('active','disabled')),role TEXT CHECK(role IS NULL OR role IN ('admin','editor','viewer')),must_change_password INTEGER NOT NULL DEFAULT 0,temporary_password_expires_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                    CREATE TABLE api_keys_v2 (id TEXT PRIMARY KEY,name TEXT NOT NULL,key_prefix TEXT NOT NULL,key_hash TEXT NOT NULL UNIQUE,scopes_json TEXT NOT NULL,expires_at TEXT,revoked_at TEXT,created_by TEXT NOT NULL REFERENCES users_v2(id),last_used_at TEXT,created_at TEXT NOT NULL);
                    CREATE TABLE knowledge_bases_v2 (id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','deleting','deleted','delete_failed')),chunk_size INTEGER NOT NULL,chunk_overlap INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                    CREATE TABLE documents_v2 (id TEXT PRIMARY KEY,knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases_v2(id),filename TEXT NOT NULL,stored_filename TEXT NOT NULL,sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,chunk_count INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL CHECK(status IN ('pending','indexing','ready','failed','deleting','deleted','delete_failed')),error_message TEXT,created_by TEXT NOT NULL REFERENCES users_v2(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(knowledge_base_id,sha256));
                    CREATE INDEX documents_kb_idx ON documents_v2(knowledge_base_id,created_at DESC);
                    CREATE TABLE audit_events_v2 (id TEXT PRIMARY KEY,actor_type TEXT NOT NULL,actor_id TEXT,action TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT,request_id TEXT NOT NULL,created_at TEXT NOT NULL,detail_json TEXT NOT NULL DEFAULT '{}');
                    """
                )
                conn.execute(
                    """INSERT INTO users_v2 SELECT u.id,u.email,u.password_hash,u.status,
                    CASE WHEN u.is_platform_admin=1 OR EXISTS(SELECT 1 FROM memberships m WHERE m.user_id=u.id AND m.status='active' AND m.role='tenant_admin') THEN 'admin'
                    WHEN EXISTS(SELECT 1 FROM memberships m WHERE m.user_id=u.id AND m.status='active' AND m.role='editor') THEN 'editor'
                    WHEN EXISTS(SELECT 1 FROM memberships m WHERE m.user_id=u.id AND m.status='active' AND m.role='viewer') THEN 'viewer' ELSE NULL END,
                    u.must_change_password,u.temporary_password_expires_at,u.created_at,u.updated_at FROM users u"""
                )
                conn.execute(
                    """INSERT INTO knowledge_bases_v2 SELECT k.id,
                    CASE WHEN (SELECT count(*) FROM knowledge_bases same WHERE same.name=k.name)>1 THEN k.name || ' - ' || t.name || ' (' || substr(k.tenant_id,1,8) || ')' ELSE k.name END,
                    k.description,k.status,k.chunk_size,k.chunk_overlap,k.created_at,k.updated_at FROM knowledge_bases k JOIN tenants t ON t.id=k.tenant_id"""
                )
                conn.execute(
                    "INSERT INTO documents_v2 SELECT id,knowledge_base_id,filename,stored_filename,sha256,size_bytes,chunk_count,status,error_message,created_by,created_at,updated_at FROM documents"
                )
                conn.execute(
                    "INSERT INTO api_keys_v2 SELECT id,name,key_prefix,key_hash,scopes_json,expires_at,COALESCE(revoked_at,?),created_by,last_used_at,created_at FROM tenant_api_keys",
                    (stamp,),
                )
                conn.execute(
                    "INSERT INTO audit_events_v2 SELECT id,actor_type,actor_id,action,resource_type,resource_id,request_id,created_at,detail_json FROM audit_events"
                )
                conn.execute("UPDATE sessions SET revoked_at=COALESCE(revoked_at,?)", (stamp,))
                conn.executescript(
                    """DROP TABLE documents; DROP TABLE tenant_api_keys; DROP TABLE memberships; DROP TABLE knowledge_bases; DROP TABLE audit_events; DROP TABLE tenants; DROP TABLE users;
                    ALTER TABLE users_v2 RENAME TO users; ALTER TABLE api_keys_v2 RENAME TO api_keys; ALTER TABLE knowledge_bases_v2 RENAME TO knowledge_bases; ALTER TABLE documents_v2 RENAME TO documents; ALTER TABLE audit_events_v2 RENAME TO audit_events;"""
                )
                conn.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(2,?)", (stamp,)
                )
                conn.commit()
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"foreign key check failed: {violations!r}")
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def many(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connection() as conn:
            return conn.execute(sql, params).rowcount

    def bootstrap_admin(self, email: str, password_hash: str) -> bool:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute(
                    "SELECT 1 FROM app_settings WHERE key='bootstrap_complete'"
                ).fetchone():
                    conn.commit()
                    return False
                stamp, user_id = now(), str(uuid4())
                conn.execute(
                    "INSERT INTO users(id,email,password_hash,status,role,created_at,updated_at) VALUES(?,?,?,'active','admin',?,?)",
                    (user_id, email.lower(), password_hash, stamp, stamp),
                )
                conn.execute(
                    "INSERT INTO app_settings(key,value) VALUES('bootstrap_complete','true')"
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def audit(
        self,
        *,
        action: str,
        resource_type: str,
        request_id: str,
        actor_type: str,
        actor_id: str | None = None,
        resource_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.run(
            "INSERT INTO audit_events(id,actor_type,actor_id,action,resource_type,resource_id,request_id,created_at,detail_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                actor_type,
                actor_id,
                action,
                resource_type,
                resource_id,
                request_id,
                now(),
                json.dumps(detail or {}),
            ),
        )

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM users WHERE email=?", (email.lower(),))

    def user(self, user_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM users WHERE id=?", (user_id,))

    def users(self) -> list[dict[str, Any]]:
        return self.many(
            "SELECT id,email,status,role,must_change_password,created_at FROM users ORDER BY email"
        )

    def create_user(
        self, email: str, password_hash: str, role: str, temporary_expires_at: str
    ) -> dict[str, Any]:
        user_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO users(id,email,password_hash,status,role,must_change_password,temporary_password_expires_at,created_at,updated_at) VALUES(?,?,?,'active',?,1,?,?,?)",
            (user_id, email.lower(), password_hash, role, temporary_expires_at, stamp, stamp),
        )
        return self.user(user_id) or {}

    def update_user(self, user_id: str, role: str | None, status: str | None) -> bool:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                if not user:
                    conn.rollback()
                    return False
                target_role, target_status = (
                    role if role is not None else user["role"],
                    status or user["status"],
                )
                if (
                    user["role"] == "admin"
                    and user["status"] == "active"
                    and (target_role != "admin" or target_status != "active")
                    and conn.execute(
                        "SELECT count(*) FROM users WHERE role='admin' AND status='active'"
                    ).fetchone()[0]
                    <= 1
                ):
                    raise ValueError("Cannot change the last active administrator")
                conn.execute(
                    "UPDATE users SET role=?,status=?,updated_at=? WHERE id=?",
                    (target_role, target_status, now(), user_id),
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def session_user(self, token_hash: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT u.*,s.id AS session_id,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'",
            (token_hash, now()),
        )

    def create_session(self, user_id: str, token_hash: str, expires_at: str) -> None:
        self.run(
            "INSERT INTO sessions(id,user_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?)",
            (str(uuid4()), user_id, token_hash, expires_at, now()),
        )

    def revoke_session(self, session_id: str) -> None:
        self.run(
            "UPDATE sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (now(), session_id),
        )

    def revoke_user_sessions(self, user_id: str) -> None:
        self.run(
            "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now(), user_id),
        )

    def change_password(self, user_id: str, password_hash: str) -> None:
        self.run(
            "UPDATE users SET password_hash=?,must_change_password=0,temporary_password_expires_at=NULL,updated_at=? WHERE id=?",
            (password_hash, now(), user_id),
        )

    def key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM api_keys WHERE key_hash=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)",
            (key_hash, now()),
        )

    def create_api_key(
        self,
        name: str,
        prefix: str,
        key_hash: str,
        scopes: list[str],
        expires_at: str | None,
        created_by: str,
    ) -> dict[str, Any]:
        key_id = str(uuid4())
        self.run(
            "INSERT INTO api_keys(id,name,key_prefix,key_hash,scopes_json,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (key_id, name, prefix, key_hash, json.dumps(scopes), expires_at, created_by, now()),
        )
        return self.key_by_id(key_id) or {}

    def key_by_id(self, key_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT id,name,key_prefix,scopes_json,expires_at,revoked_at,created_by,last_used_at,created_at FROM api_keys WHERE id=?",
            (key_id,),
        )

    def list_api_keys(self) -> list[dict[str, Any]]:
        return self.many(
            "SELECT id,name,key_prefix,scopes_json,expires_at,revoked_at,created_by,last_used_at,created_at FROM api_keys ORDER BY created_at DESC"
        )

    def revoke_api_key(self, key_id: str) -> bool:
        return (
            self.run(
                "UPDATE api_keys SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (now(), key_id),
            )
            > 0
        )

    def touch_key(self, key_id: str) -> None:
        self.run("UPDATE api_keys SET last_used_at=? WHERE id=?", (now(), key_id))

    def knowledge_bases(self) -> list[dict[str, Any]]:
        return self.many(
            "SELECT * FROM knowledge_bases WHERE status != 'deleted' ORDER BY name COLLATE NOCASE"
        )

    def knowledge_base(self, kb_id: str, active_only: bool = False) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM knowledge_bases WHERE id=?"
            + (" AND status='active'" if active_only else ""),
            (kb_id,),
        )

    def create_knowledge_base(
        self, name: str, description: str, chunk_size: int, chunk_overlap: int
    ) -> dict[str, Any]:
        kb_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO knowledge_bases(id,name,description,status,chunk_size,chunk_overlap,created_at,updated_at) VALUES(?,?,?,'active',?,?,?,?)",
            (kb_id, name, description, chunk_size, chunk_overlap, stamp, stamp),
        )
        return self.knowledge_base(kb_id) or {}

    def update_knowledge_base(self, kb_id: str, name: str | None, description: str | None) -> bool:
        kb = self.knowledge_base(kb_id, True)
        return bool(
            kb
            and self.run(
                "UPDATE knowledge_bases SET name=?,description=?,updated_at=? WHERE id=?",
                (
                    name or kb["name"],
                    description if description is not None else kb["description"],
                    now(),
                    kb_id,
                ),
            )
        )

    def set_knowledge_base_status(self, kb_id: str, status: str) -> bool:
        return (
            self.run(
                "UPDATE knowledge_bases SET status=?,updated_at=? WHERE id=?",
                (status, now(), kb_id),
            )
            > 0
        )

    def documents(self, kb_id: str) -> list[dict[str, Any]]:
        return self.many(
            "SELECT * FROM documents WHERE knowledge_base_id=? AND status != 'deleted' ORDER BY created_at DESC",
            (kb_id,),
        )

    def document(self, kb_id: str, doc_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM documents WHERE knowledge_base_id=? AND id=?", (kb_id, doc_id)
        )

    def create_document(
        self,
        kb_id: str,
        filename: str,
        stored_filename: str,
        digest: str,
        size_bytes: int,
        created_by: str,
    ) -> dict[str, Any]:
        existing = self.one(
            "SELECT id,status FROM documents WHERE knowledge_base_id=? AND sha256=?",
            (kb_id, digest),
        )
        if existing:
            if existing["status"] not in {"deleted", "failed"}:
                raise ValueError("A document with identical content already exists")
            stamp = now()
            self.run(
                "UPDATE documents SET filename=?,stored_filename=?,size_bytes=?,chunk_count=0,status='pending',error_message=NULL,created_by=?,created_at=?,updated_at=? WHERE id=?",
                (filename, stored_filename, size_bytes, created_by, stamp, stamp, existing["id"]),
            )
            return self.document(kb_id, existing["id"]) or {}
        doc_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO documents(id,knowledge_base_id,filename,stored_filename,sha256,size_bytes,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?,?)",
            (
                doc_id,
                kb_id,
                filename,
                stored_filename,
                digest,
                size_bytes,
                created_by,
                stamp,
                stamp,
            ),
        )
        return self.document(kb_id, doc_id) or {}

    def set_document_status(
        self,
        kb_id: str,
        doc_id: str,
        status: str,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        self.run(
            "UPDATE documents SET status=?,chunk_count=COALESCE(?,chunk_count),error_message=?,updated_at=? WHERE knowledge_base_id=? AND id=?",
            (status, chunk_count, error, now(), kb_id, doc_id),
        )

    def delete_document_record(self, kb_id: str, doc_id: str) -> None:
        self.run(
            "UPDATE documents SET status='deleted',updated_at=? WHERE knowledge_base_id=? AND id=?",
            (now(), kb_id, doc_id),
        )
