# Backup, restore, and upgrade

Enter a maintenance window or stop the container before copying `/data`. A backup must include the entire directory: copying only SQLite or only Chroma is not recoverable RAG state.

Restore by stopping the container, replacing the complete `/data` directory from the same backup, and starting the image version that created it. Schema migrations are applied transactionally at start-up and recorded in `schema_migrations`; take a full backup before upgrading. Changes to Chroma or the embedding model require an explicit reindex release, never a silent configuration change.
