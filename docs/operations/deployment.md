# Deployment

This release is intentionally a **single application container with one writer**. Do not run multiple replicas against the same `/data` volume: SQLite and embedded Chroma are not a horizontally scalable deployment.

1. Copy `.env.example` to `.env`, set a long unique bootstrap password, and run `docker compose up --build`.
2. Sign in with the bootstrap account, then remove `RAG_BOOTSTRAP_ADMIN_PASSWORD` from `.env`. Bootstrap is recorded in SQLite and will not create another account on restart.
3. Persist the named `rag-data` volume (or mount a host directory at `/data`). It contains `app.sqlite3`, `chroma/`, and tenant uploads; all three are one consistency unit.

The container runs as an unprivileged user and serves both the Hash History management UI and `/api/v1` from the same origin. Configure `RAG_LLM_*` only when chat generation is wanted; their values are never returned by the API.
