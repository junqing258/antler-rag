set dotenv-load := true

dev:
    #!/usr/bin/env bash
    set -euo pipefail
    (cd apps/backend && exec uv run uvicorn app:app --reload --reload-dir src --port 8001) &
    backend_pid=$!
    trap 'kill "$backend_pid" 2>/dev/null; wait "$backend_pid" 2>/dev/null || true' EXIT INT TERM
    pnpm --dir apps/frontend dev

test:
    cd apps/backend && uv run pytest
    pnpm --dir apps/frontend test

lint:
    cd apps/backend && uv run ruff check .
    pnpm --dir apps/frontend lint

format:
    cd apps/backend && uv run ruff format .
    pnpm --dir apps/frontend format

build:
    pnpm --dir apps/frontend build

docker-build:
    docker build -t antler-rag-admin .
