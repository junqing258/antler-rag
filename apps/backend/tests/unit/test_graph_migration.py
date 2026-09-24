import sqlite3
from pathlib import Path

import pytest

from db import Database


def test_v3_graph_schema_is_applied_once_with_foreign_keys_enabled(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")

    assert database.migrate() == [1, 2, 3]
    assert database.migrate() == []
    assert database.schema_version() == 3
    assert database.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='graph_builds'")
    assert database.one(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='relation_mentions'"
    )
    assert database.one("PRAGMA foreign_key_check") is None


def test_v3_failure_rolls_back_all_tables_indexes_and_migration_record(tmp_path: Path) -> None:
    class BrokenV3Database(Database):
        @staticmethod
        def _v3_statements() -> tuple[str, ...]:
            return (*Database._v3_statements(), "THIS IS NOT SQL")

    database = BrokenV3Database(tmp_path / "app.sqlite3")
    initial = Path(__file__).parents[2] / "src/db/migrations/001_initial.sql"
    with database.connection() as conn:
        conn.executescript(initial.read_text())
        conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(1,'now')")
    database._migrate_v2()

    with pytest.raises(sqlite3.OperationalError):
        database._migrate_v3()

    assert database.schema_version() == 2
    assert (
        database.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='graph_builds'")
        is None
    )
    assert (
        database.one(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='graph_builds_kb_idx'"
        )
        is None
    )


def test_database_rejects_a_newer_unknown_schema_version(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    with database.connection() as conn:
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(4,'now')")

    with pytest.raises(RuntimeError, match="newer"):
        database.migrate()
