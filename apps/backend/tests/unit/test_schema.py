import sqlite3

import pytest

from core.config import Settings
from db import Database
from db.schema import SCHEMA_COLUMNS, validate_schema
from reindex_embeddings import read_catalog


def test_current_schema_initializes_once_without_migration_history(tmp_path):
    db = Database(tmp_path / "app.sqlite3")
    db.initialize()
    tables = {row["name"] for row in db.many("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == set(SCHEMA_COLUMNS)
    db.bootstrap_admin("admin@example.com", "hash")
    kb = db.create_knowledge_base("KB", "", 900, 150, "structure")
    db.initialize()
    assert db.knowledge_base(kb["id"])["chunk_strategy"] == "structure"
    assert db.one("PRAGMA foreign_key_check") is None
    assert db.one("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'") is None
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
        db.create_knowledge_base("Invalid", "", 900, 150, "semantic")


def test_initialization_failure_rolls_back_every_schema_statement(tmp_path, monkeypatch):
    import db.repository
    from db.schema import schema_statements

    database = Database(tmp_path / "app.sqlite3")
    statements = schema_statements()
    monkeypatch.setattr(db.repository, "schema_statements", lambda: [*statements, "INVALID SQL"])
    with pytest.raises(sqlite3.OperationalError):
        database.initialize()
    assert database.one("SELECT 1 FROM sqlite_master WHERE type='table'") is None
    monkeypatch.setattr(db.repository, "schema_statements", lambda: statements)
    database.initialize()
    with database.connection() as conn:
        validate_schema(conn)


def test_noncurrent_database_is_rejected_without_conversion(tmp_path):
    db = Database(tmp_path / "app.sqlite3")
    db.run("CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT)")
    db.run("INSERT INTO tenants VALUES('tenant','Original')")
    with pytest.raises(ValueError, match="current schema"):
        db.initialize()
    assert db.one("SELECT * FROM tenants") == {"id": "tenant", "name": "Original"}
    assert len(db.many("SELECT name FROM sqlite_master WHERE type='table'")) == 1


def test_missing_current_column_is_not_silently_added(tmp_path):
    db = Database(tmp_path / "app.sqlite3")
    db.initialize()
    db.run("ALTER TABLE knowledge_bases DROP COLUMN chunk_strategy")
    with pytest.raises(ValueError, match="knowledge_bases"):
        db.initialize()
    assert "chunk_strategy" not in [
        row["name"] for row in db.many("PRAGMA table_info(knowledge_bases)")
    ]


def test_read_only_catalog_accepts_current_schema_without_version_table(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    assert read_catalog(settings) == []


def test_current_schema_accepts_reordered_columns_and_unrelated_tables(tmp_path):
    from db.schema import schema_statements

    settings = Settings(_env_file=None, data_dir=tmp_path)
    db = Database(settings.db_path)
    with db.connection() as conn:
        for statement in schema_statements():
            if statement.startswith("CREATE TABLE knowledge_bases"):
                strategy = (
                    "chunk_strategy TEXT NOT NULL DEFAULT 'recursive' "
                    "CHECK(chunk_strategy IN ('recursive','structure'))"
                )
                statement = statement.replace(f",{strategy}", "")
                statement = statement.removesuffix(")") + f",{strategy})"
            conn.execute(statement)
        conn.execute("CREATE TABLE unrelated_metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO unrelated_metadata VALUES('retained','original')")
        before = conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
        columns_before = conn.execute("PRAGMA table_info(knowledge_bases)").fetchall()

    db.initialize()
    assert read_catalog(settings) == []
    with db.connection() as conn:
        assert conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall() == before
        assert conn.execute("PRAGMA table_info(knowledge_bases)").fetchall() == columns_before
        assert conn.execute("SELECT value FROM unrelated_metadata").fetchone()[0] == "original"
    db.bootstrap_admin("admin@example.com", "hash")
    kb = db.create_knowledge_base("Current", "", 900, 150, "structure")
    assert kb["chunk_strategy"] == "structure"


def test_application_rejects_noncurrent_database_before_chroma_initialization(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    import app

    settings = Settings(_env_file=None, data_dir=tmp_path)
    db = Database(settings.db_path)
    db.run("CREATE TABLE unsupported (id TEXT)")

    def forbidden(*args, **kwargs):
        raise AssertionError("Chroma should not initialize for a noncurrent schema")

    monkeypatch.setattr(app, "RAGStore", forbidden)
    with pytest.raises(ValueError, match="current schema"), TestClient(app.create_app(settings)):
        pass
