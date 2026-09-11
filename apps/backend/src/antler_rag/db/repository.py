from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """SQLite repository. Tenant-owned lookups always take a tenant id."""

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

    def migrate(self) -> None:
        migration = Path(__file__).parent / "migrations" / "001_initial.sql"
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.executescript(migration.read_text())
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                    (now(),),
                )
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
        """Create exactly one bootstrap administrator; repeated starts are no-ops."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                done = conn.execute(
                    "SELECT 1 FROM app_settings WHERE key='bootstrap_complete'"
                ).fetchone()
                if done:
                    conn.commit()
                    return False
                stamp, user_id = now(), str(uuid4())
                conn.execute(
                    "INSERT INTO users(id,email,password_hash,status,is_platform_admin,created_at,updated_at) VALUES(?,?,?,'active',1,?,?)",
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
        tenant_id: str | None = None,
        resource_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.run(
            "INSERT INTO audit_events(id,tenant_id,actor_type,actor_id,action,resource_type,resource_id,request_id,created_at,detail_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                tenant_id,
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

    def create_tenant(self, name: str) -> dict[str, Any]:
        tenant_id, stamp = str(uuid4()), now()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO tenants(id,name,status,created_at,updated_at) VALUES(?,?,'active',?,?)",
                    (tenant_id, name, stamp, stamp),
                )
                kb_id = str(uuid4())
                conn.execute(
                    "INSERT INTO knowledge_bases(id,tenant_id,name,is_default,status,chunk_size,chunk_overlap,created_at,updated_at) VALUES(?,?, 'Default knowledge base',1,'active',900,150,?,?)",
                    (kb_id, tenant_id, stamp, stamp),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.one("SELECT * FROM tenants WHERE id=?", (tenant_id,)) or {}

    def tenant(self, tenant_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM tenants WHERE id=?", (tenant_id,))

    def active_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM tenants WHERE id=? AND status='active'", (tenant_id,))

    def update_tenant(self, tenant_id: str, name: str | None, status: str | None) -> bool:
        tenant = self.tenant(tenant_id)
        if not tenant:
            return False
        self.run(
            "UPDATE tenants SET name=?,status=?,updated_at=? WHERE id=?",
            (name or tenant["name"], status or tenant["status"], now(), tenant_id),
        )
        return True

    def list_tenants_for_user(self, user_id: str, platform_admin: bool) -> list[dict[str, Any]]:
        if platform_admin:
            return self.many("SELECT * FROM tenants ORDER BY name COLLATE NOCASE")
        return self.many(
            "SELECT t.*, m.role FROM tenants t JOIN memberships m ON m.tenant_id=t.id WHERE m.user_id=? AND m.status='active' ORDER BY t.name COLLATE NOCASE",
            (user_id,),
        )

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM users WHERE email=?", (email.lower(),))

    def user(self, user_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM users WHERE id=?", (user_id,))

    def platform_admins(self) -> list[dict[str, Any]]:
        return self.many(
            "SELECT id,email,status,created_at FROM users WHERE is_platform_admin=1 ORDER BY email"
        )

    def set_platform_admin(self, user_id: str, enabled: bool) -> bool:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                if not user:
                    conn.rollback()
                    return False
                if not enabled and user["is_platform_admin"]:
                    count = conn.execute(
                        "SELECT count(*) FROM users WHERE is_platform_admin=1 AND status='active'"
                    ).fetchone()[0]
                    if count <= 1 and user["status"] == "active":
                        raise ValueError("Cannot revoke the last active platform administrator")
                conn.execute(
                    "UPDATE users SET is_platform_admin=?,updated_at=? WHERE id=?",
                    (int(enabled), now(), user_id),
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise

    def session_user(self, token_hash: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT u.*, s.id AS session_id, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'",
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

    def membership(self, tenant_id: str, user_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM memberships WHERE tenant_id=? AND user_id=? AND status='active'",
            (tenant_id, user_id),
        )

    def list_members(self, tenant_id: str) -> list[dict[str, Any]]:
        return self.many(
            "SELECT m.*,u.email,u.status AS user_status FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.tenant_id=? ORDER BY u.email",
            (tenant_id,),
        )

    def add_member(self, tenant_id: str, user_id: str, role: str) -> dict[str, Any]:
        member_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO memberships(id,tenant_id,user_id,role,status,created_at,updated_at) VALUES(?,?,?,?,'active',?,?)",
            (member_id, tenant_id, user_id, role, stamp, stamp),
        )
        return (
            self.one("SELECT * FROM memberships WHERE id=? AND tenant_id=?", (member_id, tenant_id))
            or {}
        )

    def create_user(
        self, email: str, password_hash: str, temporary_expires_at: str
    ) -> dict[str, Any]:
        user_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO users(id,email,password_hash,status,must_change_password,temporary_password_expires_at,created_at,updated_at) VALUES(?,?,?,'active',1,?,?,?)",
            (user_id, email.lower(), password_hash, temporary_expires_at, stamp, stamp),
        )
        return self.user(user_id) or {}

    def member_by_id(self, tenant_id: str, member_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM memberships WHERE id=? AND tenant_id=?", (member_id, tenant_id)
        )

    def update_member(
        self, tenant_id: str, member_id: str, role: str | None, status: str | None
    ) -> bool:
        current = self.member_by_id(tenant_id, member_id)
        if not current:
            return False
        self.run(
            "UPDATE memberships SET role=?,status=?,updated_at=? WHERE id=? AND tenant_id=?",
            (role or current["role"], status or current["status"], now(), member_id, tenant_id),
        )
        return True

    def delete_member(self, tenant_id: str, member_id: str) -> bool:
        return (
            self.run("DELETE FROM memberships WHERE id=? AND tenant_id=?", (member_id, tenant_id))
            > 0
        )

    def key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT k.*,t.status AS tenant_status FROM tenant_api_keys k JOIN tenants t ON t.id=k.tenant_id WHERE k.key_hash=? AND k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at>?)",
            (key_hash, now()),
        )

    def create_api_key(
        self,
        tenant_id: str,
        name: str,
        prefix: str,
        key_hash: str,
        scopes: list[str],
        expires_at: str | None,
        created_by: str,
    ) -> dict[str, Any]:
        key_id = str(uuid4())
        self.run(
            "INSERT INTO tenant_api_keys(id,tenant_id,name,key_prefix,key_hash,scopes_json,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                key_id,
                tenant_id,
                name,
                prefix,
                key_hash,
                json.dumps(scopes),
                expires_at,
                created_by,
                now(),
            ),
        )
        return self.key_by_id(tenant_id, key_id) or {}

    def key_by_id(self, tenant_id: str, key_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT id,tenant_id,name,key_prefix,scopes_json,expires_at,revoked_at,created_by,last_used_at,created_at FROM tenant_api_keys WHERE tenant_id=? AND id=?",
            (tenant_id, key_id),
        )

    def list_api_keys(self, tenant_id: str) -> list[dict[str, Any]]:
        return self.many(
            "SELECT id,tenant_id,name,key_prefix,scopes_json,expires_at,revoked_at,created_by,last_used_at,created_at FROM tenant_api_keys WHERE tenant_id=? ORDER BY created_at DESC",
            (tenant_id,),
        )

    def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        return (
            self.run(
                "UPDATE tenant_api_keys SET revoked_at=? WHERE id=? AND tenant_id=? AND revoked_at IS NULL",
                (now(), key_id, tenant_id),
            )
            > 0
        )

    def touch_key(self, key_id: str) -> None:
        self.run("UPDATE tenant_api_keys SET last_used_at=? WHERE id=?", (now(), key_id))

    def knowledge_bases(self, tenant_id: str) -> list[dict[str, Any]]:
        return self.many(
            "SELECT * FROM knowledge_bases WHERE tenant_id=? AND status != 'deleted' ORDER BY is_default DESC,name COLLATE NOCASE",
            (tenant_id,),
        )

    def knowledge_base(
        self, tenant_id: str, kb_id: str, active_only: bool = False
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM knowledge_bases WHERE tenant_id=? AND id=?" + (
            " AND status='active'" if active_only else ""
        )
        return self.one(sql, (tenant_id, kb_id))

    def create_knowledge_base(
        self, tenant_id: str, name: str, description: str, chunk_size: int, chunk_overlap: int
    ) -> dict[str, Any]:
        kb_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO knowledge_bases(id,tenant_id,name,description,status,chunk_size,chunk_overlap,created_at,updated_at) VALUES(?,?,?,?,'active',?,?,?,?)",
            (kb_id, tenant_id, name, description, chunk_size, chunk_overlap, stamp, stamp),
        )
        return self.knowledge_base(tenant_id, kb_id) or {}

    def update_knowledge_base(
        self, tenant_id: str, kb_id: str, name: str | None, description: str | None
    ) -> bool:
        kb = self.knowledge_base(tenant_id, kb_id, active_only=True)
        if not kb:
            return False
        self.run(
            "UPDATE knowledge_bases SET name=?,description=?,updated_at=? WHERE tenant_id=? AND id=?",
            (
                name or kb["name"],
                description if description is not None else kb["description"],
                now(),
                tenant_id,
                kb_id,
            ),
        )
        return True

    def set_knowledge_base_status(self, tenant_id: str, kb_id: str, status: str) -> bool:
        return (
            self.run(
                "UPDATE knowledge_bases SET status=?,updated_at=? WHERE tenant_id=? AND id=?",
                (status, now(), tenant_id, kb_id),
            )
            > 0
        )

    def documents(self, tenant_id: str, kb_id: str) -> list[dict[str, Any]]:
        return self.many(
            "SELECT * FROM documents WHERE tenant_id=? AND knowledge_base_id=? AND status != 'deleted' ORDER BY created_at DESC",
            (tenant_id, kb_id),
        )

    def document(self, tenant_id: str, kb_id: str, doc_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM documents WHERE tenant_id=? AND knowledge_base_id=? AND id=?",
            (tenant_id, kb_id, doc_id),
        )

    def create_document(
        self,
        tenant_id: str,
        kb_id: str,
        filename: str,
        stored_filename: str,
        digest: str,
        size_bytes: int,
        created_by: str,
    ) -> dict[str, Any]:
        doc_id, stamp = str(uuid4()), now()
        self.run(
            "INSERT INTO documents(id,tenant_id,knowledge_base_id,filename,stored_filename,sha256,size_bytes,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',?,?,?)",
            (
                doc_id,
                tenant_id,
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
        return self.document(tenant_id, kb_id, doc_id) or {}

    def set_document_status(
        self,
        tenant_id: str,
        kb_id: str,
        doc_id: str,
        status: str,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        self.run(
            "UPDATE documents SET status=?,chunk_count=COALESCE(?,chunk_count),error_message=?,updated_at=? WHERE tenant_id=? AND knowledge_base_id=? AND id=?",
            (status, chunk_count, error, now(), tenant_id, kb_id, doc_id),
        )

    def delete_document_record(self, tenant_id: str, kb_id: str, doc_id: str) -> None:
        self.run(
            "UPDATE documents SET status='deleted',updated_at=? WHERE tenant_id=? AND knowledge_base_id=? AND id=?",
            (now(), tenant_id, kb_id, doc_id),
        )
