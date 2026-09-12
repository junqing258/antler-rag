from pathlib import Path

import pytest

from antler_rag.db import Database


def test_bootstrap_creates_global_admin_without_default_knowledge_base(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.migrate()
    assert db.migrate() == []
    assert db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin and admin["role"] == "admin"
    assert db.knowledge_bases() == []


def test_last_active_admin_cannot_be_downgraded_or_disabled(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.migrate()
    db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin
    with pytest.raises(ValueError, match="last active"):
        db.update_user(admin["id"], "viewer", None)
    with pytest.raises(ValueError, match="last active"):
        db.update_user(admin["id"], None, "disabled")


@pytest.mark.parametrize("stale_status", ["deleted", "failed"])
def test_reupload_reuses_a_deleted_or_failed_document_record(tmp_path: Path, stale_status: str) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.migrate()
    db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin
    knowledge_base = db.create_knowledge_base("Knowledge Base", "", 900, 150)
    first = db.create_document(
        knowledge_base["id"], "old.pdf", "old.pdf", "a" * 64, 10, admin["id"]
    )
    db.set_document_status(knowledge_base["id"], first["id"], stale_status, 3, "Old failure")

    reuploaded = db.create_document(
        knowledge_base["id"], "new.pdf", "new.pdf", "a" * 64, 20, admin["id"]
    )

    assert reuploaded["id"] == first["id"]
    assert reuploaded["filename"] == "new.pdf"
    assert reuploaded["stored_filename"] == "new.pdf"
    assert reuploaded["size_bytes"] == 20
    assert reuploaded["chunk_count"] == 0
    assert reuploaded["status"] == "pending"
    assert reuploaded["error_message"] is None


def test_v2_migrates_multiple_default_knowledge_bases_and_revokes_credentials(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite3"
    legacy = Database(db_path)
    migration = Path(__file__).parents[2] / "src/antler_rag/db/migrations/001_initial.sql"
    with legacy.connection() as conn:
        conn.executescript(migration.read_text())
        conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(1,'now')")
        conn.execute("INSERT INTO users VALUES('u','a@example.com','hash','active',1,0,NULL,'now','now')")
        for tenant_id in ("t1", "t2"):
            conn.execute("INSERT INTO tenants VALUES(?,?, 'active','now','now')", (tenant_id, tenant_id))
            conn.execute("INSERT INTO knowledge_bases VALUES(?,?, 'Shared', '',1,'active',900,150,'now','now')", (f"kb-{tenant_id}", tenant_id))
        conn.execute("INSERT INTO tenant_api_keys VALUES('key','t1','key','prefix','hash','[\"retrieve\"]',NULL,NULL,'u',NULL,'now')")
        conn.execute("INSERT INTO sessions VALUES('session','u','session-hash','2999-01-01T00:00:00+00:00',NULL,'now')")
    applied = legacy.migrate()
    assert applied == [2]
    assert [kb["name"] for kb in legacy.knowledge_bases()] == ["Shared - t1 (t1)", "Shared - t2 (t2)"]
    assert legacy.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tenants'") is None
    assert legacy.one("SELECT revoked_at FROM api_keys WHERE id='key'")["revoked_at"]
    assert legacy.one("SELECT revoked_at FROM sessions WHERE id='session'")["revoked_at"]
    assert legacy.one("PRAGMA foreign_key_check") is None
