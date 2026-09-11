set dotenv-load := true

dev:
    (cd apps/backend && uv run uvicorn antler_rag.app:app --reload --port 8001) & pnpm --dir apps/frontend dev

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
