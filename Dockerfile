FROM node:22-alpine AS frontend
WORKDIR /workspace
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/frontend/package.json apps/frontend/package.json
RUN corepack enable && pnpm install --frozen-lockfile
COPY apps/frontend apps/frontend
RUN pnpm --dir apps/frontend build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 \
    XDG_CACHE_HOME=/app/.cache
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/backend/src src
COPY --from=frontend /workspace/apps/frontend/dist src/antler_rag/static
RUN uv sync --frozen --no-dev && mkdir -p /data /app/.cache && chown -R app:app /data /app
USER app
ENV RAG_DATA_DIR=/data
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "antler_rag.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
