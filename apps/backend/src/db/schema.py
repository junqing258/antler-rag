"""The application's current SQLite schema; no version upgrades or conversion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_COLUMNS = {
    "api_keys": (
        "id",
        "name",
        "key_prefix",
        "key_hash",
        "scopes_json",
        "expires_at",
        "revoked_at",
        "created_by",
        "last_used_at",
        "created_at",
    ),
    "app_settings": ("key", "value"),
    "audit_events": (
        "id",
        "actor_type",
        "actor_id",
        "action",
        "resource_type",
        "resource_id",
        "request_id",
        "created_at",
        "detail_json",
    ),
    "documents": (
        "id",
        "knowledge_base_id",
        "filename",
        "stored_filename",
        "sha256",
        "size_bytes",
        "chunk_count",
        "status",
        "error_message",
        "created_by",
        "created_at",
        "updated_at",
    ),
    "entities": (
        "id",
        "knowledge_base_id",
        "canonical_name",
        "normalized_name",
        "entity_type",
        "created_at",
        "updated_at",
    ),
    "entity_aliases": ("id", "entity_id", "normalized_alias"),
    "entity_mentions": (
        "id",
        "entity_id",
        "knowledge_base_id",
        "document_id",
        "chunk_id",
        "start_offset",
        "end_offset",
    ),
    "graph_builds": (
        "id",
        "knowledge_base_id",
        "requested_by",
        "status",
        "extractor_model",
        "extractor_version",
        "schema_version",
        "requested_at",
        "started_at",
        "finished_at",
        "error_code",
    ),
    "graph_document_states": (
        "knowledge_base_id",
        "document_id",
        "build_id",
        "source_sha256",
        "status",
        "extractor_model",
        "extractor_version",
        "indexed_at",
        "error_code",
        "updated_at",
    ),
    "knowledge_bases": (
        "id",
        "name",
        "description",
        "status",
        "chunk_size",
        "chunk_overlap",
        "chunk_strategy",
        "created_at",
        "updated_at",
    ),
    "relation_mentions": (
        "id",
        "relation_id",
        "knowledge_base_id",
        "document_id",
        "chunk_id",
        "build_id",
    ),
    "relations": (
        "id",
        "knowledge_base_id",
        "subject_entity_id",
        "predicate",
        "object_entity_id",
        "confidence",
        "extractor_model",
        "extractor_version",
        "created_at",
        "updated_at",
    ),
    "sessions": ("id", "user_id", "token_hash", "expires_at", "revoked_at", "created_at"),
    "users": (
        "id",
        "email",
        "password_hash",
        "status",
        "role",
        "must_change_password",
        "temporary_password_expires_at",
        "created_at",
        "updated_at",
    ),
}


def schema_statements() -> list[str]:
    return [
        statement.strip()
        for statement in Path(__file__).with_suffix(".sql").read_text().split(";")
        if statement.strip()
    ]


def validate_schema(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_tables = set(SCHEMA_COLUMNS) - tables
    if missing_tables:
        raise ValueError(
            f"Database is missing current schema tables: {', '.join(sorted(missing_tables))}"
        )
    for table, expected in SCHEMA_COLUMNS.items():
        # Queries name their columns. Physical order and unrelated tables do not
        # affect the current schema, and need no conversion or version lookup.
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        if columns != set(expected):
            missing = sorted(set(expected) - columns)
            extra = sorted(columns - set(expected))
            raise ValueError(
                f"Database table {table} does not match the current schema "
                f"(missing columns: {missing}, unexpected columns: {extra})"
            )
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Database foreign key check failed")
