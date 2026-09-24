from __future__ import annotations

import hashlib
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pwdlib import PasswordHash
from pydantic import AliasChoices, BaseModel, Field

from config import Settings
from db import Database
from db.repository import now
from documents import UnsupportedDocument, extract_text
from rag import Evidence, RAGStore, RetrievalService, RetrievedChunk
from rag.agentic import AgentService
from rag.store import RerankerError, upload_path

password_hash = PasswordHash.recommended()
ROLES = {"admin", "editor", "viewer"}
WRITE_ROLES = {"admin", "editor"}
SCOPES = {"retrieve", "chat", "documents:read",
          "documents:write", "documents:delete", "agentic:query"}

logger = logging.getLogger("antler_rag")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def token_digest(
    token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()


def expiry(hours: int) -> str: return (datetime.now(UTC) +
                                       timedelta(hours=hours)).isoformat()


class APIError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class UserCreate(BaseModel):
    email: str
    role: Literal["admin", "editor", "viewer"]
    initial_password: str = Field(min_length=12, max_length=256)


class UserPatch(BaseModel):
    role: Literal["admin", "editor", "viewer"] | None = None
    status: Literal["active", "disabled"] | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["retrieve", "chat"])
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    chunk_size: int = Field(default=900, ge=100, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)


class KnowledgeBasePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class RetrieveRequest(BaseModel):
    knowledge_base_id: str
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None, max_length=100)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    rerank: bool = False


class ChatRequest(RetrieveRequest):
    # Chat clients use `message`; retain `query` so existing integrations keep working.
    query: str = Field(
        min_length=1,
        max_length=10_000,
        validation_alias=AliasChoices("message", "query"),
    )
    system_prompt: str | None = Field(default=None, max_length=5000)


class AgenticRagRequest(BaseModel):
    knowledge_base_id: str
    message: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["auto", "vector", "keyword", "graph", "hybrid"] = "auto"
    include_trace: bool = False


class Principal(BaseModel):
    actor_type: Literal["user", "api_key"]
    actor_id: str
    user_id: str | None = None
    role: str | None = None
    must_change_password: bool = False
    session_id: str | None = None
    scopes: set[str] = Field(default_factory=set)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {key: user[key] for key in ("id", "email", "status", "role", "must_change_password", "created_at") if key in user}


def public_key(key: dict[str, Any]) -> dict[str, Any]:
    item = {name: value for name, value in key.items() if name != "key_hash"}
    item["scopes"] = json.loads(item.pop("scopes_json"))
    return item


def chunk_payload(chunk: RetrievedChunk | Evidence) -> dict[str, str | float | int | None]:
    return {"chunk_id": chunk.chunk_id, "document_id": chunk.document_id, "knowledge_base_id": chunk.knowledge_base_id, "filename": chunk.filename, "content": chunk.content, "distance": chunk.distance, "chunk_index": chunk.chunk_index, "rerank_score": chunk.rerank_score}


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
            database.bootstrap_admin(settings.bootstrap_admin_email, password_hash.hash(
                settings.bootstrap_admin_password))
        app.state.settings, app.state.db, app.state.store = settings, database, RAGStore(settings)
        app.state.retrieval = RetrievalService.from_store(app.state.store)
        app.state.agentic = AgentService(app.state.retrieval, settings)
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="Antler RAG Admin API",
                  version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except APIError as error:
            response = JSONResponse(status_code=error.status_code, content={
                                    "code": error.code, "message": error.message, "request_id": request_id})
        except HTTPException as error:
            response = JSONResponse(status_code=error.status_code, content={"code": "http_error", "message": error.detail if isinstance(
                error.detail, str) else "Request failed", "request_id": request_id})
        except Exception as error:
            logger.exception("api_request_unhandled request_id=%s method=%s path=%s error_type=%s",
                             request_id, request.method, request.url.path, type(error).__name__)
            raise
        response.headers["x-request-id"] = request_id
        logger.info("api_request_completed request_id=%s method=%s path=%s status=%s duration_ms=%d", request_id,
                    request.method, request.url.path, response.status_code, (perf_counter() - started) * 1000)
        return response

    def db() -> Database: return app.state.db
    def store() -> RAGStore: return app.state.store
    def retrieval() -> RetrievalService: return app.state.retrieval
    def agentic() -> AgentService: return app.state.agentic

    def session_principal(authorization: Annotated[str | None, Header()] = None, database: Database = Depends(db)) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise APIError("authentication_required",
                           "Authentication is required", 401)
        user = database.session_user(token_digest(
            authorization.removeprefix("Bearer ").strip()))
        if not user:
            raise APIError("invalid_session",
                           "Session is invalid or expired", 401)
        return Principal(actor_type="user", actor_id=user["id"], user_id=user["id"], role=user["role"], must_change_password=bool(user["must_change_password"]), session_id=user["session_id"])

    def normal_session(principal: Principal = Depends(session_principal)) -> Principal:
        if principal.must_change_password:
            raise APIError("password_change_required",
                           "Change the initial password before continuing", 403)
        if principal.role not in ROLES:
            raise APIError("account_not_authorized",
                           "This account has not been granted workspace access", 403)
        return principal

    def access(required_scope: str | None = None, roles: set[str] | None = None):
        def dependency(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None, authorization: Annotated[str | None, Header()] = None, database: Database = Depends(db)) -> Principal:
            if x_api_key:
                if not required_scope:
                    raise APIError("insufficient_scope",
                                   "API keys cannot access this endpoint", 403)
                key = database.key_by_hash(token_digest(x_api_key))
                if not key:
                    raise APIError(
                        "invalid_api_key", "API key is invalid, expired, or revoked", 401)
                scopes = set(json.loads(key["scopes_json"]))
                if required_scope not in scopes:
                    raise APIError(
                        "insufficient_scope", "The API key does not grant this operation", 403)
                database.touch_key(key["id"])
                return Principal(actor_type="api_key", actor_id=key["id"], user_id=key["created_by"], scopes=scopes)
            if not authorization or not authorization.startswith("Bearer "):
                raise APIError("authentication_required",
                               "Authentication is required", 401)
            user = database.session_user(token_digest(
                authorization.removeprefix("Bearer ").strip()))
            if not user:
                raise APIError("invalid_session",
                               "Session is invalid or expired", 401)
            if user["must_change_password"]:
                raise APIError("password_change_required",
                               "Change the initial password before continuing", 403)
            if user["role"] not in ROLES:
                raise APIError(
                    "account_not_authorized", "This account has not been granted workspace access", 403)
            if roles and user["role"] not in roles:
                raise APIError(
                    "forbidden", "You do not have permission for this operation", 403)
            return Principal(actor_type="user", actor_id=user["id"], user_id=user["id"], role=user["role"], session_id=user["session_id"])
        return dependency

    def administrator(principal: Principal = Depends(normal_session)) -> Principal:
        if principal.role != "admin":
            raise APIError(
                "forbidden", "Administrator permission is required", 403)
        return principal

    def audit(request: Request, principal: Principal, action: str, resource_type: str, resource_id: str | None = None) -> None:
        app.state.db.audit(action=action, resource_type=resource_type, resource_id=resource_id, request_id=request.headers.get(
            "x-request-id", "unknown"), actor_type=principal.actor_type, actor_id=principal.actor_id)

    @app.get("/health/live")
    def live() -> dict[str, str]: return {"status": "ok"}

    @app.get("/health/ready")
    def ready(database: Database = Depends(db), rag: RAGStore = Depends(
        store)) -> dict[str, str]: database.one("SELECT 1"); rag.healthy(); return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request, database: Database = Depends(db)) -> dict[str, Any]:
        user = database.user_by_email(payload.email)
        if not user or user["status"] != "active" or not password_hash.verify(payload.password, user["password_hash"]):
            raise APIError("invalid_credentials",
                           "Email or password is incorrect", 401)
        if user["must_change_password"] and user["temporary_password_expires_at"] and user["temporary_password_expires_at"] <= now():
            raise APIError("temporary_password_expired",
                           "The initial password has expired; ask an administrator to reset it", 403)
        if user["role"] not in ROLES:
            raise APIError("account_not_authorized",
                           "This account has not been granted workspace access", 403)
        token = secrets.token_urlsafe(32)
        database.create_session(user["id"], token_digest(
            token), expiry(settings.session_hours))
        database.audit(action="login", resource_type="session", request_id=request.headers.get(
            "x-request-id", "unknown"), actor_type="user", actor_id=user["id"])
        return {"token": token, "user": public_user(user)}

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, principal: Principal = Depends(session_principal), database: Database = Depends(db)) -> None:
        database.revoke_session(principal.session_id or "")
        audit(request, principal, "logout", "session")

    @app.get("/api/v1/auth/me")
    def me(principal: Principal = Depends(session_principal), database: Database = Depends(db)) -> dict[str, Any]: return {
        "user": public_user(database.user(principal.user_id or "") or {}), "must_change_password": principal.must_change_password}

    @app.post("/api/v1/auth/change-password", status_code=204)
    def change_password(payload: ChangePasswordRequest, request: Request, principal: Principal = Depends(session_principal), database: Database = Depends(db)) -> None:
        user = database.user(principal.user_id or "")
        if not user or not password_hash.verify(payload.current_password, user["password_hash"]):
            raise APIError("invalid_credentials",
                           "Current password is incorrect", 401)
        database.change_password(
            user["id"], password_hash.hash(payload.new_password))
        database.revoke_user_sessions(user["id"])
        audit(request, principal, "change_password", "user", user["id"])

    @app.get("/api/v1/users")
    def list_users(_: Principal = Depends(administrator), database: Database = Depends(
        db)) -> dict[str, Any]: return {"items": database.users()}

    @app.post("/api/v1/users", status_code=201)
    def create_user(payload: UserCreate, request: Request, principal: Principal = Depends(administrator), database: Database = Depends(db)) -> dict[str, Any]:
        try:
            user = database.create_user(payload.email, password_hash.hash(
                payload.initial_password), payload.role, expiry(settings.temporary_password_hours))
        except Exception as error:
            raise APIError(
                "conflict", "A user with this email already exists", 409) from error
        audit(request, principal, "create", "user", user["id"])
        return public_user(user)

    @app.patch("/api/v1/users/{user_id}")
    def patch_user(user_id: str, payload: UserPatch, request: Request, principal: Principal = Depends(administrator), database: Database = Depends(db)) -> dict[str, Any]:
        try:
            changed = database.update_user(
                user_id, payload.role, payload.status)
        except ValueError as error:
            raise APIError("last_active_admin", str(error), 409) from error
        if not changed:
            raise APIError("not_found", "User was not found", 404)
        audit(request, principal, "update", "user", user_id)
        return public_user(database.user(user_id) or {})

    @app.get("/api/v1/api-keys")
    def list_api_keys(_: Principal = Depends(administrator), database: Database = Depends(
        db)) -> dict[str, Any]: return {"items": [public_key(key) for key in database.list_api_keys()]}

    @app.post("/api/v1/api-keys", status_code=201)
    def create_api_key(payload: ApiKeyCreate, request: Request, principal: Principal = Depends(administrator), database: Database = Depends(db)) -> dict[str, Any]:
        if not set(payload.scopes).issubset(SCOPES) or not payload.scopes:
            raise APIError("validation_error",
                           "Unknown or empty API key scopes", 422)
        raw = f"ark_{secrets.token_urlsafe(32)}"
        key = database.create_api_key(payload.name, raw[:12], token_digest(raw), sorted(set(payload.scopes)), expiry(
            payload.expires_in_days * 24) if payload.expires_in_days else None, principal.user_id or "")
        audit(request, principal, "create", "api_key", key["id"])
        return {**public_key(key), "api_key": raw}

    @app.delete("/api/v1/api-keys/{key_id}", status_code=204)
    def delete_api_key(key_id: str, request: Request, principal: Principal = Depends(administrator), database: Database = Depends(db)) -> None:
        if not database.revoke_api_key(key_id):
            raise APIError("not_found", "API key was not found", 404)
        audit(request, principal, "revoke", "api_key", key_id)

    @app.get("/api/v1/knowledge-bases")
    def list_knowledge_bases(principal: Principal = Depends(access(roles=ROLES)), database: Database = Depends(db)) -> dict[str, Any]:
        if principal.actor_type == "api_key":
            raise APIError("insufficient_scope",
                           "API keys cannot enumerate knowledge bases", 403)
        return {"items": database.knowledge_bases()}

    @app.post("/api/v1/knowledge-bases", status_code=201)
    def create_knowledge_base(payload: KnowledgeBaseCreate, request: Request, principal: Principal = Depends(access(roles=WRITE_ROLES)), database: Database = Depends(db)) -> dict[str, Any]:
        if payload.chunk_overlap >= payload.chunk_size:
            raise APIError("validation_error",
                           "chunk_overlap must be smaller than chunk_size", 422)
        try:
            kb = database.create_knowledge_base(
                payload.name, payload.description, payload.chunk_size, payload.chunk_overlap)
        except Exception as error:
            raise APIError(
                "conflict", "A knowledge base with this name already exists", 409) from error
        audit(request, principal, "create", "knowledge_base", kb["id"])
        return kb

    @app.get("/api/v1/knowledge-bases/{knowledge_base_id}")
    def get_knowledge_base(knowledge_base_id: str, _: Principal = Depends(access(roles=ROLES)), database: Database = Depends(db)) -> dict[str, Any]:
        kb = database.knowledge_base(knowledge_base_id, True)
        if not kb:
            raise APIError("not_found", "Knowledge base was not found", 404)
        return kb

    @app.patch("/api/v1/knowledge-bases/{knowledge_base_id}")
    def patch_knowledge_base(knowledge_base_id: str, payload: KnowledgeBasePatch, request: Request, principal: Principal = Depends(access(roles=WRITE_ROLES)), database: Database = Depends(db)) -> dict[str, Any]:
        if not database.update_knowledge_base(knowledge_base_id, payload.name, payload.description):
            raise APIError("not_found", "Knowledge base was not found", 404)
        audit(request, principal, "update",
              "knowledge_base", knowledge_base_id)
        return database.knowledge_base(knowledge_base_id) or {}

    @app.delete("/api/v1/knowledge-bases/{knowledge_base_id}", status_code=202)
    def delete_knowledge_base(knowledge_base_id: str, request: Request, principal: Principal = Depends(access(roles=WRITE_ROLES)), database: Database = Depends(db), rag: RAGStore = Depends(store)) -> dict[str, str]:
        if not database.knowledge_base(knowledge_base_id):
            raise APIError("not_found", "Knowledge base was not found", 404)
        database.set_knowledge_base_status(knowledge_base_id, "deleting")
        try:
            for document in database.documents(knowledge_base_id):
                rag.delete_document(knowledge_base_id, document["id"])
                upload_path(settings.uploads_dir, knowledge_base_id,
                            document["stored_filename"]).unlink(missing_ok=True)
                database.delete_document_record(
                    knowledge_base_id, document["id"])
            rag.delete_knowledge_base(knowledge_base_id)
            database.set_knowledge_base_status(knowledge_base_id, "deleted")
        except Exception as error:
            database.set_knowledge_base_status(
                knowledge_base_id, "delete_failed")
            raise APIError(
                "delete_failed", "Knowledge base cleanup failed and can be retried", 500) from error
        audit(request, principal, "delete",
              "knowledge_base", knowledge_base_id)
        return {"status": "deleted"}

    def validate_retrieve(payload: RetrieveRequest, database: Database) -> None:
        if not database.knowledge_base(payload.knowledge_base_id, True):
            raise APIError("not_found", "Knowledge base was not found", 404)
        for document_id in payload.document_ids or []:
            if not database.document(payload.knowledge_base_id, document_id):
                raise APIError("not_found", "Document was not found", 404)

    @app.get("/api/v1/knowledge-bases/{knowledge_base_id}/documents")
    def list_documents(knowledge_base_id: str, _: Principal = Depends(access("documents:read", ROLES)), database: Database = Depends(db)) -> dict[str, Any]:
        if not database.knowledge_base(knowledge_base_id, True):
            raise APIError("not_found", "Knowledge base was not found", 404)
        return {"items": database.documents(knowledge_base_id)}

    @app.post("/api/v1/knowledge-bases/{knowledge_base_id}/documents", status_code=201)
    async def upload_documents(knowledge_base_id: str, files: Annotated[list[UploadFile], File()], request: Request, principal: Principal = Depends(access("documents:write", WRITE_ROLES)), database: Database = Depends(db), rag: RAGStore = Depends(store)) -> dict[str, Any]:
        kb = database.knowledge_base(knowledge_base_id, True)
        if not kb:
            raise APIError("not_found", "Knowledge base was not found", 404)
        if len(files) > settings.max_files_per_request:
            raise APIError(
                "too_many_files", f"At most {settings.max_files_per_request} files are allowed", 413)
        indexed: list[dict[str, Any]] = []
        for upload in files:
            content = await upload.read()
            filename = Path(upload.filename or "upload").name
            document: dict[str, Any] | None = None
            destination: Path | None = None
            try:
                if len(content) > settings.max_upload_bytes:
                    raise APIError(
                        "file_too_large", f"Each file must be at most {settings.max_upload_bytes} bytes", 413)
                digest, stored = hashlib.sha256(content).hexdigest(
                ), f"{uuid4()}{Path(filename).suffix.lower()}"
                document = database.create_document(
                    knowledge_base_id, filename, stored, digest, len(content), principal.user_id or "")
                destination = upload_path(
                    settings.uploads_dir, knowledge_base_id, stored)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                database.set_document_status(
                    knowledge_base_id, document["id"], "indexing")
                logger.info("document_index_started request_id=%s knowledge_base_id=%s document_id=%s size_bytes=%d",
                            request.state.request_id, knowledge_base_id, document["id"], len(content))
                chunks = rag.index(knowledge_base_id=knowledge_base_id, document_id=document["id"], filename=filename, text=extract_text(
                    filename, content), chunk_size=kb["chunk_size"], chunk_overlap=kb["chunk_overlap"], digest=digest)
                database.set_document_status(
                    knowledge_base_id, document["id"], "ready", chunks)
                indexed.append(database.document(
                    knowledge_base_id, document["id"]) or {})
                audit(request, principal, "create", "document", document["id"])
                logger.info("document_index_completed request_id=%s knowledge_base_id=%s document_id=%s chunk_count=%d",
                            request.state.request_id, knowledge_base_id, document["id"], chunks)
            except APIError:
                raise
            except (UnsupportedDocument, ValueError) as error:
                logger.warning("document_index_rejected request_id=%s knowledge_base_id=%s document_id=%s error_type=%s",
                               request.state.request_id, knowledge_base_id, document["id"] if document else None, type(error).__name__)
                if document:
                    database.set_document_status(
                        knowledge_base_id, document["id"], "failed", error=str(error))
                    rag.delete_document(knowledge_base_id, document["id"])
                if destination:
                    destination.unlink(missing_ok=True)
                raise APIError("invalid_document", str(error), 422) from error
            except Exception as error:
                logger.exception("document_index_failed request_id=%s knowledge_base_id=%s document_id=%s error_type=%s",
                                 request.state.request_id, knowledge_base_id, document["id"] if document else None, type(error).__name__)
                if document:
                    database.set_document_status(
                        knowledge_base_id, document["id"], "failed", error="Indexing failed")
                    rag.delete_document(knowledge_base_id, document["id"])
                if destination:
                    destination.unlink(missing_ok=True)
                raise APIError("indexing_failed",
                               "Document indexing failed", 500) from error
            finally:
                await upload.close()
        return {"documents": indexed}

    @app.get("/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    def get_document(knowledge_base_id: str, document_id: str, _: Principal = Depends(access("documents:read", ROLES)), database: Database = Depends(db)) -> dict[str, Any]:
        document = database.document(knowledge_base_id, document_id)
        if not document:
            raise APIError("not_found", "Document was not found", 404)
        return document

    @app.delete("/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}", status_code=204)
    def delete_document(knowledge_base_id: str, document_id: str, request: Request, principal: Principal = Depends(access("documents:delete", WRITE_ROLES)), database: Database = Depends(db), rag: RAGStore = Depends(store)) -> None:
        document = database.document(knowledge_base_id, document_id)
        if not document:
            raise APIError("not_found", "Document was not found", 404)
        database.set_document_status(
            knowledge_base_id, document_id, "deleting")
        try:
            rag.delete_document(knowledge_base_id, document_id)
            upload_path(settings.uploads_dir, knowledge_base_id,
                        document["stored_filename"]).unlink(missing_ok=True)
            database.delete_document_record(knowledge_base_id, document_id)
        except Exception as error:
            database.set_document_status(
                knowledge_base_id, document_id, "delete_failed")
            raise APIError(
                "delete_failed", "Document cleanup failed and can be retried", 500) from error
        audit(request, principal, "delete", "document", document_id)

    @app.post("/api/v1/retrieve")
    def retrieve(payload: RetrieveRequest, _: Principal = Depends(access("retrieve", ROLES)), database: Database = Depends(db), service: RetrievalService = Depends(retrieval)) -> dict[str, Any]:
        validate_retrieve(payload, database)
        try:
            chunks = service.retrieve(knowledge_base_id=payload.knowledge_base_id, query=payload.query, top_k=payload.top_k, document_ids=payload.document_ids, score_threshold=payload.score_threshold, rerank=payload.rerank)
        except RerankerError as error:
            raise APIError("reranker_unavailable", str(error), 503) from error
        return {"results": [chunk_payload(chunk) for chunk in chunks]}

    @app.post("/api/v1/chat")
    async def chat(payload: ChatRequest, request: Request, _: Principal = Depends(access("chat", ROLES)), database: Database = Depends(db), service: RetrievalService = Depends(retrieval)) -> dict[str, Any]:
        validate_retrieve(payload, database)
        try:
            chunks = service.retrieve(knowledge_base_id=payload.knowledge_base_id,
                                  query=payload.query, top_k=payload.top_k, document_ids=payload.document_ids,
                                  score_threshold=payload.score_threshold, rerank=payload.rerank)
        except RerankerError as error:
            raise APIError("reranker_unavailable", str(error), 503) from error
        sources = [chunk_payload(chunk) for chunk in chunks]
        if not settings.llm_base_url or not settings.chat_model:
            return {"answer": None, "sources": sources, "detail": "LLM is not configured; use sources as Agent context."}
        prompt = payload.system_prompt or "Answer only from the provided sources. If they do not answer the question, say so and cite source numbers."
        source_text = "\n\n".join(
            f"[Source {index}: {chunk.filename}]\n{chunk.content}" for index, chunk in enumerate(chunks, 1))
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
                response = await client.post(f"{settings.llm_base_url.rstrip('/')}/chat/completions", json={"model": settings.chat_model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": f"Sources:\n{source_text}\n\nQuestion: {payload.query}"}], "temperature": 0}, headers=headers)
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, IndexError) as error:
            status_code = error.response.status_code if isinstance(
                error, httpx.HTTPStatusError) else None
            logger.warning("chat_request_failed request_id=%s model=%s status=%s error_type=%s duration_ms=%d",
                           request.state.request_id, settings.chat_model, status_code, type(error).__name__, (perf_counter() - started) * 1000)
            raise APIError("llm_failed", "LLM request failed", 502) from error
        logger.info("chat_request_completed request_id=%s model=%s duration_ms=%d",
                    request.state.request_id, settings.chat_model, (perf_counter() - started) * 1000)
        return {"answer": answer, "sources": sources}

    @app.post("/api/v1/agentic-rag")
    async def agentic_rag(payload: AgenticRagRequest, request: Request, principal: Principal = Depends(access("agentic:query", ROLES)), database: Database = Depends(db), agent: AgentService = Depends(agentic)) -> dict[str, Any]:
        validate_retrieve(
            RetrieveRequest(
                knowledge_base_id=payload.knowledge_base_id,
                query=payload.message,
                top_k=payload.top_k,
            ),
            database,
        )
        if not settings.agentic_enabled:
            raise APIError("feature_disabled", "Agentic retrieval is disabled", 503)
        if payload.mode not in {"auto", "vector"}:
            raise APIError("feature_disabled", f"Retrieval mode '{payload.mode}' is unavailable", 503)
        result = await agent.answer(
            knowledge_base_id=payload.knowledge_base_id,
            message=payload.message,
            top_k=payload.top_k,
            mode=payload.mode,
        )
        response: dict[str, Any] = {
            "answer": result.answer,
            "sources": [chunk_payload(item) for item in result.evidence],
            "retrieval_mode": "vector",
        }
        if result.detail:
            response["detail"] = result.detail
        if payload.include_trace:
            response["trace_id"] = str(uuid4())
            response["trace"] = {
                "steps": [
                    {
                        "name": step.name,
                        "tool": step.tool,
                        "candidate_count": step.candidate_count,
                        "duration_ms": step.duration_ms,
                        "error_code": step.error_code,
                        "evidence_ids": list(step.evidence_ids),
                    }
                    for step in result.trace
                ]
            }
        audit(request, principal, "agentic_query", "knowledge_base", payload.knowledge_base_id)
        return response

    app.mount("/", StaticFiles(directory=Path(__file__).parent /
              "static", html=True), name="frontend")
    return app


app = create_app()
