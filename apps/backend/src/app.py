"""Application composition root.

HTTP endpoints live in :mod:`routers`; this module owns only process lifecycle,
cross-cutting middleware, and static-file mounting. It continues to export the
request schemas used by older integrations.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import Settings
from db import Database
from models.schemas import (
    AgenticRagRequest,
    ApiKeyCreate,
    ChangePasswordRequest,
    ChatRequest,
    GraphRebuildRequest,
    GraphSearchRequest,
    KnowledgeBaseCreate,
    KnowledgeBasePatch,
    LoginRequest,
    Principal,
    RetrieveRequest,
    UserCreate,
    UserPatch,
)
from rag import RAGStore, RetrievalService
from rag.agentic import AgentService
from rag.graph_build import GraphBuildService
from rag.graph_store import GraphStore
from routers import ALL_ROUTERS
from services.errors import APIError
from utils.logging import configure_logging
from utils.security import (
    ROLES,
    SCOPES,
    WRITE_ROLES,
    chunk_payload,
    expiry,
    new_request_id,
    password_hash,
    public_key,
    public_user,
    token_digest,
)

logger = configure_logging()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.db_path)
        if database.schema_version() == 1:
            raise RuntimeError(
                "Legacy multi-tenant data detected; stop the service, back up the complete data directory, "
                "then run `python -m migrate_single_workspace --data-dir ... --confirm`"
            )
        database.migrate()
        if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
            database.bootstrap_admin(
                settings.bootstrap_admin_email,
                password_hash.hash(settings.bootstrap_admin_password),
            )
        app.state.settings = settings
        app.state.db = database
        app.state.store = RAGStore(settings)
        app.state.retrieval = RetrievalService.from_store(app.state.store)
        app.state.agentic = AgentService(app.state.retrieval, settings)
        app.state.graph_store = GraphStore(database)
        app.state.graph_build = GraphBuildService(
            database, app.state.store, app.state.graph_store, settings
        )
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="Antler RAG Admin API", version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or new_request_id()
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except APIError as error:
            response = JSONResponse(
                status_code=error.status_code,
                content={"code": error.code, "message": error.message, "request_id": request_id},
            )
        except HTTPException as error:
            response = JSONResponse(
                status_code=error.status_code,
                content={
                    "code": "http_error",
                    "message": error.detail if isinstance(error.detail, str) else "Request failed",
                    "request_id": request_id,
                },
            )
        except Exception as error:
            logger.exception(
                "api_request_unhandled request_id={request_id} method={method} path={path} "
                "error_type={error_type}",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error_type=type(error).__name__,
            )
            raise
        response.headers["x-request-id"] = request_id
        logger.info(
            "api_request_completed request_id={request_id} method={method} path={path} "
            "status={status} duration_ms={duration_ms:.0f}",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return response

    for router in ALL_ROUTERS:
        app.include_router(router)
    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="frontend"
    )
    return app


app = create_app()

__all__ = [
    "ROLES",
    "SCOPES",
    "WRITE_ROLES",
    "APIError",
    "AgenticRagRequest",
    "ApiKeyCreate",
    "ChangePasswordRequest",
    "ChatRequest",
    "GraphRebuildRequest",
    "GraphSearchRequest",
    "KnowledgeBaseCreate",
    "KnowledgeBasePatch",
    "LoginRequest",
    "Principal",
    "RetrieveRequest",
    "UserCreate",
    "UserPatch",
    "app",
    "chunk_payload",
    "create_app",
    "expiry",
    "new_request_id",
    "password_hash",
    "public_key",
    "public_user",
    "token_digest",
]
