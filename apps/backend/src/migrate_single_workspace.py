"""Preflight and execute the one-time v1-to-v2 workspace migration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.config import Settings
from db import Database
from migration import rebuild_chroma, stage_legacy_uploads
from rag import RAGStore


def report(database: Database) -> dict[str, object]:
    version = database.schema_version()
    if version != 1:
        return {"schema_version": version, "migration_required": False}
    with database.connection() as conn:
        tenants = conn.execute("SELECT count(*) FROM tenants").fetchone()[0]
        documents = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        keys = conn.execute("SELECT count(*) FROM tenant_api_keys WHERE revoked_at IS NULL").fetchone()[0]
        sessions = conn.execute("SELECT count(*) FROM sessions WHERE revoked_at IS NULL").fetchone()[0]
        collisions = [dict(row) for row in conn.execute("SELECT name,count(*) AS count FROM knowledge_bases GROUP BY name HAVING count(*) > 1 ORDER BY name")]
    return {"schema_version": 1, "migration_required": True, "tenants": tenants, "documents": documents, "active_api_keys_to_revoke": keys, "active_sessions_to_revoke": sessions, "knowledge_base_name_collisions": collisions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="The complete RAG data directory")
    parser.add_argument("--dry-run", action="store_true", help="Print a migration report without changing data")
    parser.add_argument("--confirm", action="store_true", help="Apply the migration; service must be stopped and data backed up")
    args = parser.parse_args()
    if args.dry_run == args.confirm:
        parser.error("select exactly one of --dry-run or --confirm")
    settings = Settings(data_dir=args.data_dir)
    database = Database(settings.db_path)
    print(json.dumps(report(database), ensure_ascii=False, indent=2))
    if args.dry_run or database.schema_version() >= 2:
        return
    staged = stage_legacy_uploads(settings, database)
    database.migrate()
    if staged:
        rebuild_chroma(settings, database, RAGStore(settings))


if __name__ == "__main__":
    main()
