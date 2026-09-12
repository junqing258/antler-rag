# Backup, restore, and upgrade

Enter a maintenance window or stop the container before copying `/data`. A backup must include the entire directory: copying only SQLite or only Chroma is not recoverable RAG state.

Restore by stopping the container, replacing the complete `/data` directory from the same backup, and starting the image version that created it. SQLite schema migrations are applied transactionally at start-up and recorded in `schema_migrations`; take a full backup before upgrading. The v2 single-workspace migration additionally copies legacy uploads and rebuilds Chroma, so it must run in a maintenance window and be validated against that backup before production cutover. Changes to Chroma or the embedding model require an explicit reindex release, never a silent configuration change. After setting the new embedding configuration, run `cd apps/backend && uv run python -m antler_rag.reindex_embeddings --confirm` during the maintenance window.
