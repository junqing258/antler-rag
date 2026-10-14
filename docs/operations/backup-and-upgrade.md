# Backup, restore, and current-schema operation

Stop the service and every other writer before copying the complete data directory. SQLite, Chroma, uploads and graph provenance form one consistency unit. Restore the entire directory with the application build that created it; restoring only one component does not recover consistent RAG state.

## Database initialization

The application uses one current schema in `apps/backend/src/db/schema.sql`. Startup calls `Database.initialize()`: an empty database is created transactionally from this schema; a nonempty database is validated for the required current tables and column names. Physical column order and unrelated extra tables do not affect validation; no tables are converted or removed. There are no numbered migrations, migration-history tables, tenant conversion tools, or backward-compatible module/API aliases.

If an existing directory does not match the current schema, keep it and its backup intact. Start with a new data directory, recreate knowledge bases/users/API keys as needed, and reupload original source files. Do not run the current service against a differently shaped database expecting automatic upgrades. The application never automatically deletes or resets existing data.

Only current-format Chroma records are read. They must contain `chunk_strategy`, `chunker_version`, and `heading_path_json`. Optional page/line/element/section fields remain absent when they genuinely do not apply, such as recursive chunks. Reindex an otherwise current-schema database from its original uploads when its vector records need replacement.

## Strategy configuration and rebuilding embeddings

Knowledge-base creation supports `recursive` (default) and `structure`, with character budgets and overlap. Configuration is fixed after creation. To change strategy, create a new knowledge base, reupload source files and validate retrieval before removing the prior knowledge base.

Full embedding rebuilds require a maintenance window, a complete backup, one maintenance process, and all other writers stopped:

1. Confirm the database already uses the current schema and the source files are available. Set the intended external embedding configuration. This CLI retains the external embedding-model requirement; normal uploads also support Chroma's default embedding.
2. Run a read-only preflight:

   ```bash
   cd apps/backend
   uv run python -m reindex_embeddings --data-dir /data --dry-run
   ```

   The command opens SQLite using `mode=ro`, validates current tables/columns, checks persisted strategies and character budgets, reads original files, verifies SHA256, and reports chunk counts/errors. It does not initialize the database/Chroma, embed, or change document/graph state. A missing database or incompatible schema is rejected. `--dry-run` and `--confirm` are mutually exclusive.
3. Resolve every preflight failure. Targets include ready documents and retained pending/indexing/failed documents so interrupted rebuilds can be retried. A failed first upload may have no source copy: reupload or delete that failed record before a full rebuild.
4. Run `uv run python -m reindex_embeddings --data-dir /data --confirm`. It revalidates files/configuration and deletes the **entire active collection**. It is not a single-knowledge-base rebuild. Before deletion, affected documents become `indexing` and old graph states become `stale`, preventing interrupted documents from claiming to be ready.
5. Inspect document states and chunk counts. Successful documents become ready with graph state `not_built` in one SQLite transaction. Regenerate graph facts through the existing administrator graph-rebuild flow. Resolve vector/graph cleanup failures or restore the complete backup before reopening traffic.

SQLite/Chroma replacement uses failure compensation, not an atomic switch across storage engines. Rebuild failures keep existing source files for retry. First-upload failures delete only the newly created server copy. Same-SHA reuploads restore a retained source reference on failure and remove its unreferenced copy only after success. Cleanup failures are recorded in the document error message; successful indexing remains committed if deleting an old unreferenced source fails.

The Python API exposes `RAGStore.index_drafts()` as the sole low-level vector write interface. Use `DocumentIndexingService` for lifecycle-managed indexing. Imports use `core.config`, `utils.documents`, and `models.schemas` directly. `/chat` requires `message`; `/retrieve` requires `query`.
