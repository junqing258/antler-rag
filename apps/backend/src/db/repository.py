from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schema import schema_statements, validate_schema


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

    def initialize(self) -> None:
        """Create the current schema only in an empty database, otherwise validate it."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
                ).fetchone()
                if not existing:
                    for statement in schema_statements():
                        conn.execute(statement)
                validate_schema(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

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
        self,
        name: str,
        description: str,
        chunk_size: int,
        chunk_overlap: int,
        chunk_strategy: str = "recursive",
    ) -> dict[str, Any]:
        kb_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO knowledge_bases(id,name,description,status,chunk_size,chunk_overlap,chunk_strategy,created_at,updated_at) VALUES(?,?,?,'active',?,?,?,?,?)",
            (kb_id, name, description, chunk_size, chunk_overlap, chunk_strategy, stamp, stamp),
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

    def set_document_ready_in_tx(
        self,
        conn: sqlite3.Connection,
        *,
        knowledge_base_id: str,
        document_id: str,
        chunk_count: int,
        expected_sha256: str,
    ) -> None:
        updated = conn.execute(
            """UPDATE documents SET status='ready',chunk_count=?,error_message=NULL,updated_at=?
               WHERE knowledge_base_id=? AND id=? AND status='indexing' AND sha256=?""",
            (chunk_count, now(), knowledge_base_id, document_id, expected_sha256),
        ).rowcount
        if updated != 1:
            raise ValueError("Document state or SHA256 changed while indexing")

    def restore_document_source(self, kb_id: str, doc_id: str, snapshot: dict[str, Any]) -> None:
        self.run(
            """UPDATE documents SET stored_filename=?,filename=?,size_bytes=?,updated_at=?
               WHERE knowledge_base_id=? AND id=?""",
            (
                snapshot["stored_filename"],
                snapshot["filename"],
                snapshot["size_bytes"],
                now(),
                kb_id,
                doc_id,
            ),
        )

    def delete_document_record(self, kb_id: str, doc_id: str) -> None:
        self.run(
            "UPDATE documents SET status='deleted',updated_at=? WHERE knowledge_base_id=? AND id=?",
            (now(), kb_id, doc_id),
        )
