from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pwdlib import PasswordHash
from pydantic import BaseModel, Field

from .config import Settings
from .db import Database
from .db.repository import now
from .documents import UnsupportedDocument, extract_text
from .rag import RAGStore, RetrievedChunk
from .rag.store import upload_path

password_hash = PasswordHash.recommended()
ROLES = {"tenant_admin", "editor", "viewer"}
SCOPES = {"retrieve", "chat", "documents:read", "documents:write", "documents:delete"}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def expiry(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


class APIError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "disabled"] | None = None


class PlatformAdminCreate(BaseModel):
    user_id: str


class MemberCreate(BaseModel):
    mode: Literal["new_user", "existing_user"]
    role: Literal["tenant_admin", "editor", "viewer"]
    email: str
    initial_password: str | None = Field(default=None, min_length=12, max_length=256)


class MemberPatch(BaseModel):
    role: Literal["tenant_admin", "editor", "viewer"] | None = None
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


class ChatRequest(RetrieveRequest):
    system_prompt: str | None = Field(default=None, max_length=5000)


class Principal(BaseModel):
    actor_type: Literal["user", "api_key"]
    actor_id: str
    user_id: str | None = None
    is_platform_admin: bool = False
    must_change_password: bool = False
    session_id: str | None = None
    scopes: set[str] = Field(default_factory=set)


class TenantContext(BaseModel):
    principal: Principal
    tenant_id: str
    role: str | None = None


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        key: user[key]
        for key in (
            "id",
            "email",
            "status",
            "is_platform_admin",
            "must_change_password",
            "created_at",
        )
        if key in user
    }


def public_key(key: dict[str, Any]) -> dict[str, Any]:
    item = {name: value for name, value in key.items() if name not in {"key_hash"}}
    item["scopes"] = json.loads(item.pop("scopes_json"))
    return item


def chunk_payload(chunk: RetrievedChunk) -> dict[str, str | float | int | None]:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "knowledge_base_id": chunk.knowledge_base_id,
        "filename": chunk.filename,
        "content": chunk.content,
        "distance": chunk.distance,
        "chunk_index": chunk.chunk_index,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        db.migrate()
        app.state.settings, app.state.db, app.state.store = settings, db, RAGStore(settings)
        if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
            db.bootstrap_admin(
                settings.bootstrap_admin_email,
                password_hash.hash(settings.bootstrap_admin_password),
            )
            db.ensure_initial_tenant()
        yield

    app = FastAPI(title="Antler RAG Admin API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        try:
            response = await call_next(request)
        except APIError as error:
            response = JSONResponse(
                status_code=error.status_code,
                content={"code": error.code, "message": error.message, "request_id": request_id},
            )
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, str) else "Request failed"
            response = JSONResponse(
                status_code=error.status_code,
                content={"code": "http_error", "message": detail, "request_id": request_id},
            )
        response.headers["x-request-id"] = request_id
        return response

    def db() -> Database:
        return app.state.db

    def store() -> RAGStore:
        return app.state.store

    def session_principal(
        authorization: Annotated[str | None, Header()] = None, database: Database = Depends(db)
    ) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise APIError("authentication_required", "Authentication is required", 401)
        user = database.session_user(token_digest(authorization.removeprefix("Bearer ").strip()))
        if not user:
            raise APIError("invalid_session", "Session is invalid or expired", 401)
        return Principal(
            actor_type="user",
            actor_id=user["id"],
            user_id=user["id"],
            is_platform_admin=bool(user["is_platform_admin"]),
            must_change_password=bool(user["must_change_password"]),
            session_id=user["session_id"],
        )

    def unrestricted_session(principal: Principal = Depends(session_principal)) -> Principal:
        return principal

    def normal_session(principal: Principal = Depends(session_principal)) -> Principal:
        if principal.must_change_password:
            raise APIError(
                "password_change_required", "Change the initial password before continuing", 403
            )
        return principal

    def tenant_context(required_scope: str | None = None, roles: set[str] | None = None):
        def dependency(
            x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
            x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
            authorization: Annotated[str | None, Header()] = None,
            database: Database = Depends(db),
        ) -> TenantContext:
            if x_api_key:
                if not required_scope:
                    raise APIError(
                        "insufficient_scope", "API keys cannot access management endpoints", 403
                    )
                key = database.key_by_hash(token_digest(x_api_key))
                if not key or key["tenant_status"] != "active":
                    raise APIError(
                        "invalid_api_key",
                        "API key is invalid, expired, or its tenant is disabled",
                        401,
                    )
                scopes = set(json.loads(key["scopes_json"]))
                if required_scope and required_scope not in scopes:
                    raise APIError(
                        "insufficient_scope", "The API key does not grant this operation", 403
                    )
                database.touch_key(key["id"])
                return TenantContext(
                    principal=Principal(
                        actor_type="api_key",
                        actor_id=key["id"],
                        user_id=key["created_by"],
                        scopes=scopes,
                    ),
                    tenant_id=key["tenant_id"],
                )
            if not authorization or not authorization.startswith("Bearer "):
                raise APIError("authentication_required", "Authentication is required", 401)
            user = database.session_user(
                token_digest(authorization.removeprefix("Bearer ").strip())
            )
            if not user:
                raise APIError("invalid_session", "Session is invalid or expired", 401)
            if user["must_change_password"]:
                raise APIError(
                    "password_change_required", "Change the initial password before continuing", 403
                )
            if not x_tenant_id:
                raise APIError("tenant_required", "X-Tenant-ID is required", 400)
            tenant = database.active_tenant(x_tenant_id)
            if not tenant:
                raise APIError("tenant_not_found", "Tenant was not found", 404)
            principal = Principal(
                actor_type="user",
                actor_id=user["id"],
                user_id=user["id"],
                is_platform_admin=bool(user["is_platform_admin"]),
                session_id=user["session_id"],
            )
            membership = database.membership(x_tenant_id, user["id"])
            if not principal.is_platform_admin and not membership:
                raise APIError("tenant_not_found", "Tenant was not found", 404)
            role = membership["role"] if membership else "platform_admin"
            if roles and not principal.is_platform_admin and role not in roles:
                raise APIError("forbidden", "You do not have permission for this operation", 403)
            return TenantContext(principal=principal, tenant_id=x_tenant_id, role=role)

        return dependency

    def platform_admin(principal: Principal = Depends(normal_session)) -> Principal:
        if not principal.is_platform_admin:
            raise APIError("forbidden", "Platform administrator permission is required", 403)
        return principal

    def audit(
        request: Request,
        context: TenantContext | Principal,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
    ) -> None:
        principal = context.principal if isinstance(context, TenantContext) else context
        app.state.db.audit(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request.headers.get("x-request-id", "unknown"),
            actor_type=principal.actor_type,
            actor_id=principal.actor_id,
            tenant_id=context.tenant_id if isinstance(context, TenantContext) else None,
        )

    @app.get("/health/live", tags=["system"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["system"])
    def ready(database: Database = Depends(db), rag: RAGStore = Depends(store)) -> dict[str, str]:
        database.one("SELECT 1")
        rag.healthy()
        return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    def login(
        payload: LoginRequest, request: Request, database: Database = Depends(db)
    ) -> dict[str, Any]:
        user = database.user_by_email(payload.email)
        if (
            not user
            or user["status"] != "active"
            or not password_hash.verify(payload.password, user["password_hash"])
        ):
            raise APIError("invalid_credentials", "Email or password is incorrect", 401)
        if (
            user["must_change_password"]
            and user["temporary_password_expires_at"]
            and user["temporary_password_expires_at"] <= now()
        ):
            raise APIError(
                "temporary_password_expired",
                "The initial password has expired; ask a tenant administrator to reset it",
                403,
            )
        raw_token = secrets.token_urlsafe(32)
        database.create_session(user["id"], token_digest(raw_token), expiry(settings.session_hours))
        database.audit(
            action="login",
            resource_type="session",
            request_id=request.headers.get("x-request-id", "unknown"),
            actor_type="user",
            actor_id=user["id"],
        )
        return {"token": raw_token, "user": public_user(user)}

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(
        request: Request,
        principal: Principal = Depends(unrestricted_session),
        database: Database = Depends(db),
    ) -> None:
        database.revoke_session(principal.session_id or "")
        database.audit(
            action="logout",
            resource_type="session",
            request_id=request.headers.get("x-request-id", "unknown"),
            actor_type="user",
            actor_id=principal.actor_id,
        )

    @app.get("/api/v1/auth/me")
    def me(
        principal: Principal = Depends(unrestricted_session), database: Database = Depends(db)
    ) -> dict[str, Any]:
        return {
            "user": public_user(database.user(principal.user_id or "") or {}),
            "must_change_password": principal.must_change_password,
        }

    @app.get("/api/v1/auth/me/tenants")
    def my_tenants(
        principal: Principal = Depends(normal_session), database: Database = Depends(db)
    ) -> dict[str, Any]:
        return {
            "items": database.list_tenants_for_user(
                principal.user_id or "", principal.is_platform_admin
            )
        }

    @app.post("/api/v1/auth/change-password", status_code=204)
    def change_password(
        payload: ChangePasswordRequest,
        request: Request,
        principal: Principal = Depends(unrestricted_session),
        database: Database = Depends(db),
    ) -> None:
        user = database.user(principal.user_id or "")
        if not user or not password_hash.verify(payload.current_password, user["password_hash"]):
            raise APIError("invalid_credentials", "Current password is incorrect", 401)
        database.change_password(user["id"], password_hash.hash(payload.new_password))
        database.revoke_user_sessions(user["id"])
        database.audit(
            action="change_password",
            resource_type="user",
            resource_id=user["id"],
            request_id=request.headers.get("x-request-id", "unknown"),
            actor_type="user",
            actor_id=user["id"],
        )

    @app.get("/api/v1/tenants")
    def list_tenants(
        _: Principal = Depends(platform_admin), database: Database = Depends(db)
    ) -> dict[str, Any]:
        return {"items": database.many("SELECT * FROM tenants ORDER BY name COLLATE NOCASE")}

    @app.post("/api/v1/tenants", status_code=201)
    def create_tenant(
        payload: TenantCreate,
        request: Request,
        principal: Principal = Depends(platform_admin),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        tenant = database.create_tenant(payload.name)
        audit(request, principal, "create", "tenant", tenant["id"])
        return tenant

    @app.patch("/api/v1/tenants/{tenant_id}")
    def patch_tenant(
        tenant_id: str,
        payload: TenantPatch,
        request: Request,
        principal: Principal = Depends(platform_admin),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if not database.update_tenant(tenant_id, payload.name, payload.status):
            raise APIError("not_found", "Tenant was not found", 404)
        audit(request, principal, "update", "tenant", tenant_id)
        return database.tenant(tenant_id) or {}

    @app.get("/api/v1/platform-admins")
    def list_platform_admins(
        _: Principal = Depends(platform_admin), database: Database = Depends(db)
    ) -> dict[str, Any]:
        return {"items": database.platform_admins()}

    @app.post("/api/v1/platform-admins", status_code=204)
    def add_platform_admin(
        payload: PlatformAdminCreate,
        request: Request,
        principal: Principal = Depends(platform_admin),
        database: Database = Depends(db),
    ) -> None:
        if not database.set_platform_admin(payload.user_id, True):
            raise APIError("not_found", "User was not found", 404)
        audit(request, principal, "grant_platform_admin", "user", payload.user_id)

    @app.delete("/api/v1/platform-admins/{user_id}", status_code=204)
    def remove_platform_admin(
        user_id: str,
        request: Request,
        principal: Principal = Depends(platform_admin),
        database: Database = Depends(db),
    ) -> None:
        try:
            changed = database.set_platform_admin(user_id, False)
        except ValueError as error:
            raise APIError("last_platform_admin", str(error), 409) from error
        if not changed:
            raise APIError("not_found", "User was not found", 404)
        audit(request, principal, "revoke_platform_admin", "user", user_id)

    @app.get("/api/v1/members")
    def list_members(
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        return {"items": database.list_members(context.tenant_id)}

    @app.post("/api/v1/members", status_code=201)
    def create_member(
        payload: MemberCreate,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        try:
            if payload.mode == "new_user":
                if not payload.initial_password:
                    raise APIError(
                        "validation_error", "initial_password is required for a new user", 422
                    )
                user = database.create_user(
                    payload.email,
                    password_hash.hash(payload.initial_password),
                    expiry(settings.temporary_password_hours),
                )
            else:
                user = database.user_by_email(payload.email)
                if not user:
                    raise APIError("not_found", "Existing user was not found", 404)
            member = database.add_member(context.tenant_id, user["id"], payload.role)
        except Exception as error:
            if isinstance(error, APIError):
                raise
            raise APIError(
                "conflict", "This user is already a member or email already exists", 409
            ) from error
        audit(request, context, "create", "membership", member["id"])
        return member

    @app.patch("/api/v1/members/{membership_id}")
    def patch_member(
        membership_id: str,
        payload: MemberPatch,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if not database.update_member(
            context.tenant_id, membership_id, payload.role, payload.status
        ):
            raise APIError("not_found", "Member was not found", 404)
        audit(request, context, "update", "membership", membership_id)
        return database.member_by_id(context.tenant_id, membership_id) or {}

    @app.delete("/api/v1/members/{membership_id}", status_code=204)
    def delete_member(
        membership_id: str,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> None:
        if not database.delete_member(context.tenant_id, membership_id):
            raise APIError("not_found", "Member was not found", 404)
        audit(request, context, "delete", "membership", membership_id)

    @app.get("/api/v1/api-keys")
    def list_api_keys(
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        return {"items": [public_key(key) for key in database.list_api_keys(context.tenant_id)]}

    @app.post("/api/v1/api-keys", status_code=201)
    def create_api_key(
        payload: ApiKeyCreate,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if not set(payload.scopes).issubset(SCOPES) or not payload.scopes:
            raise APIError("validation_error", "Unknown or empty API key scopes", 422)
        raw = f"ark_{secrets.token_urlsafe(32)}"
        key = database.create_api_key(
            context.tenant_id,
            payload.name,
            raw[:12],
            token_digest(raw),
            sorted(set(payload.scopes)),
            expiry(payload.expires_in_days * 24) if payload.expires_in_days else None,
            context.principal.user_id or "",
        )
        audit(request, context, "create", "api_key", key["id"])
        return {**public_key(key), "api_key": raw}

    @app.delete("/api/v1/api-keys/{key_id}", status_code=204)
    def delete_api_key(
        key_id: str,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin"})),
        database: Database = Depends(db),
    ) -> None:
        if not database.revoke_api_key(context.tenant_id, key_id):
            raise APIError("not_found", "API key was not found", 404)
        audit(request, context, "revoke", "api_key", key_id)

    @app.get("/api/v1/knowledge-bases")
    def list_knowledge_bases(
        context: TenantContext = Depends(tenant_context(roles=ROLES)),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if context.principal.actor_type == "api_key":
            raise APIError("insufficient_scope", "API keys cannot enumerate knowledge bases", 403)
        return {"items": database.knowledge_bases(context.tenant_id)}

    @app.post("/api/v1/knowledge-bases", status_code=201)
    def create_knowledge_base(
        payload: KnowledgeBaseCreate,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin", "editor"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if payload.chunk_overlap >= payload.chunk_size:
            raise APIError("validation_error", "chunk_overlap must be smaller than chunk_size", 422)
        try:
            kb = database.create_knowledge_base(
                context.tenant_id,
                payload.name,
                payload.description,
                payload.chunk_size,
                payload.chunk_overlap,
            )
        except Exception as error:
            raise APIError(
                "conflict", "A knowledge base with this name already exists", 409
            ) from error
        audit(request, context, "create", "knowledge_base", kb["id"])
        return kb

    @app.get("/api/v1/knowledge-bases/{knowledge_base_id}")
    def get_knowledge_base(
        knowledge_base_id: str,
        context: TenantContext = Depends(tenant_context(roles=ROLES)),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        kb = database.knowledge_base(context.tenant_id, knowledge_base_id, active_only=True)
        if not kb:
            raise APIError("not_found", "Knowledge base was not found", 404)
        return kb

    @app.patch("/api/v1/knowledge-bases/{knowledge_base_id}")
    def patch_knowledge_base(
        knowledge_base_id: str,
        payload: KnowledgeBasePatch,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin", "editor"})),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if not database.update_knowledge_base(
            context.tenant_id, knowledge_base_id, payload.name, payload.description
        ):
            raise APIError("not_found", "Knowledge base was not found", 404)
        audit(request, context, "update", "knowledge_base", knowledge_base_id)
        return database.knowledge_base(context.tenant_id, knowledge_base_id) or {}

    @app.delete("/api/v1/knowledge-bases/{knowledge_base_id}", status_code=202)
    def delete_knowledge_base(
        knowledge_base_id: str,
        request: Request,
        context: TenantContext = Depends(tenant_context(roles={"tenant_admin", "editor"})),
        database: Database = Depends(db),
        rag: RAGStore = Depends(store),
    ) -> dict[str, str]:
        kb = database.knowledge_base(context.tenant_id, knowledge_base_id)
        if not kb:
            raise APIError("not_found", "Knowledge base was not found", 404)
        if kb["is_default"]:
            raise APIError(
                "default_knowledge_base", "The default knowledge base cannot be deleted", 409
            )
        database.set_knowledge_base_status(context.tenant_id, knowledge_base_id, "deleting")
        try:
            for document in database.documents(context.tenant_id, knowledge_base_id):
                rag.delete_document(context.tenant_id, knowledge_base_id, document["id"])
                upload_path(
                    settings.tenants_dir,
                    context.tenant_id,
                    knowledge_base_id,
                    document["stored_filename"],
                ).unlink(missing_ok=True)
                database.delete_document_record(
                    context.tenant_id, knowledge_base_id, document["id"]
                )
            rag.delete_knowledge_base(context.tenant_id, knowledge_base_id)
            database.set_knowledge_base_status(context.tenant_id, knowledge_base_id, "deleted")
        except Exception as error:
            database.set_knowledge_base_status(
                context.tenant_id, knowledge_base_id, "delete_failed"
            )
            raise APIError(
                "delete_failed", "Knowledge base cleanup failed and can be retried", 500
            ) from error
        audit(request, context, "delete", "knowledge_base", knowledge_base_id)
        return {"status": "deleted"}

    @app.get("/api/v1/knowledge-bases/{knowledge_base_id}/documents")
    def list_documents(
        knowledge_base_id: str,
        context: TenantContext = Depends(tenant_context("documents:read", ROLES)),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        if not database.knowledge_base(context.tenant_id, knowledge_base_id, active_only=True):
            raise APIError("not_found", "Knowledge base was not found", 404)
        return {"items": database.documents(context.tenant_id, knowledge_base_id)}

    @app.post("/api/v1/knowledge-bases/{knowledge_base_id}/documents", status_code=201)
    async def upload_documents(
        knowledge_base_id: str,
        files: Annotated[list[UploadFile], File()],
        request: Request,
        context: TenantContext = Depends(
            tenant_context("documents:write", {"tenant_admin", "editor"})
        ),
        database: Database = Depends(db),
        rag: RAGStore = Depends(store),
    ) -> dict[str, Any]:
        kb = database.knowledge_base(context.tenant_id, knowledge_base_id, active_only=True)
        if not kb:
            raise APIError("not_found", "Knowledge base was not found", 404)
        if len(files) > settings.max_files_per_request:
            raise APIError(
                "too_many_files", f"At most {settings.max_files_per_request} files are allowed", 413
            )
        indexed: list[dict[str, Any]] = []
        for upload in files:
            content = await upload.read()
            filename = Path(upload.filename or "upload").name
            document: dict[str, Any] | None = None
            destination: Path | None = None
            try:
                if len(content) > settings.max_upload_bytes:
                    raise APIError(
                        "file_too_large",
                        f"Each file must be at most {settings.max_upload_bytes} bytes",
                        413,
                    )
                digest, stored = (
                    hashlib.sha256(content).hexdigest(),
                    f"{uuid4()}{Path(filename).suffix.lower()}",
                )
                document = database.create_document(
                    context.tenant_id,
                    knowledge_base_id,
                    filename,
                    stored,
                    digest,
                    len(content),
                    context.principal.user_id or "",
                )
                destination = upload_path(
                    settings.tenants_dir, context.tenant_id, knowledge_base_id, stored
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                database.set_document_status(
                    context.tenant_id, knowledge_base_id, document["id"], "indexing"
                )
                chunks = rag.index(
                    tenant_id=context.tenant_id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=document["id"],
                    filename=filename,
                    text=extract_text(filename, content),
                    chunk_size=kb["chunk_size"],
                    chunk_overlap=kb["chunk_overlap"],
                    digest=digest,
                )
                database.set_document_status(
                    context.tenant_id, knowledge_base_id, document["id"], "ready", chunks
                )
                indexed.append(
                    database.document(context.tenant_id, knowledge_base_id, document["id"]) or {}
                )
                audit(request, context, "create", "document", document["id"])
            except APIError:
                raise
            except (UnsupportedDocument, ValueError) as error:
                if document:
                    database.set_document_status(
                        context.tenant_id,
                        knowledge_base_id,
                        document["id"],
                        "failed",
                        error=str(error),
                    )
                    rag.delete_document(context.tenant_id, knowledge_base_id, document["id"])
                if destination:
                    destination.unlink(missing_ok=True)
                raise APIError("invalid_document", str(error), 422) from error
            except Exception as error:
                if document:
                    database.set_document_status(
                        context.tenant_id,
                        knowledge_base_id,
                        document["id"],
                        "failed",
                        error="Indexing failed",
                    )
                    rag.delete_document(context.tenant_id, knowledge_base_id, document["id"])
                if destination:
                    destination.unlink(missing_ok=True)
                raise APIError("indexing_failed", "Document indexing failed", 500) from error
            finally:
                await upload.close()
        return {"documents": indexed}

    @app.get("/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    def get_document(
        knowledge_base_id: str,
        document_id: str,
        context: TenantContext = Depends(tenant_context("documents:read", ROLES)),
        database: Database = Depends(db),
    ) -> dict[str, Any]:
        document = database.document(context.tenant_id, knowledge_base_id, document_id)
        if not document:
            raise APIError("not_found", "Document was not found", 404)
        return document

    @app.delete(
        "/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}", status_code=204
    )
    def delete_document(
        knowledge_base_id: str,
        document_id: str,
        request: Request,
        context: TenantContext = Depends(
            tenant_context("documents:delete", {"tenant_admin", "editor"})
        ),
        database: Database = Depends(db),
        rag: RAGStore = Depends(store),
    ) -> None:
        document = database.document(context.tenant_id, knowledge_base_id, document_id)
        if not document:
            raise APIError("not_found", "Document was not found", 404)
        database.set_document_status(context.tenant_id, knowledge_base_id, document_id, "deleting")
        try:
            rag.delete_document(context.tenant_id, knowledge_base_id, document_id)
            upload_path(
                settings.tenants_dir,
                context.tenant_id,
                knowledge_base_id,
                document["stored_filename"],
            ).unlink(missing_ok=True)
            database.delete_document_record(context.tenant_id, knowledge_base_id, document_id)
        except Exception as error:
            database.set_document_status(
                context.tenant_id, knowledge_base_id, document_id, "delete_failed"
            )
            raise APIError(
                "delete_failed", "Document cleanup failed and can be retried", 500
            ) from error
        audit(request, context, "delete", "document", document_id)

    def validate_retrieve(
        request: RetrieveRequest, context: TenantContext, database: Database
    ) -> None:
        if not database.knowledge_base(
            context.tenant_id, request.knowledge_base_id, active_only=True
        ):
            raise APIError("not_found", "Knowledge base was not found", 404)
        for document_id in request.document_ids or []:
            if not database.document(context.tenant_id, request.knowledge_base_id, document_id):
                raise APIError("not_found", "Document was not found", 404)

    @app.post("/api/v1/retrieve")
    def retrieve(
        payload: RetrieveRequest,
        context: TenantContext = Depends(tenant_context("retrieve", ROLES)),
        database: Database = Depends(db),
        rag: RAGStore = Depends(store),
    ) -> dict[str, Any]:
        validate_retrieve(payload, context, database)
        return {
            "results": [
                chunk_payload(chunk)
                for chunk in rag.retrieve(
                    tenant_id=context.tenant_id,
                    knowledge_base_id=payload.knowledge_base_id,
                    query=payload.query,
                    top_k=payload.top_k,
                    document_ids=payload.document_ids,
                )
            ]
        }

    @app.post("/api/v1/chat")
    async def chat(
        payload: ChatRequest,
        context: TenantContext = Depends(tenant_context("chat", ROLES)),
        database: Database = Depends(db),
        rag: RAGStore = Depends(store),
    ) -> dict[str, Any]:
        validate_retrieve(payload, context, database)
        chunks = rag.retrieve(
            tenant_id=context.tenant_id,
            knowledge_base_id=payload.knowledge_base_id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
        sources = [chunk_payload(chunk) for chunk in chunks]
        if not settings.llm_base_url or not settings.llm_model:
            return {
                "answer": None,
                "sources": sources,
                "detail": "LLM is not configured; use sources as Agent context.",
            }
        system_prompt = (
            payload.system_prompt
            or "Answer only from the provided sources. If they do not answer the question, say so and cite source numbers."
        )
        source_text = "\n\n".join(
            f"[Source {index}: {chunk.filename}]\n{chunk.content}"
            for index, chunk in enumerate(chunks, 1)
        )
        headers = (
            {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
                response = await client.post(
                    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": f"Sources:\n{source_text}\n\nQuestion: {payload.query}",
                            },
                        ],
                        "temperature": 0,
                    },
                    headers=headers,
                )
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, IndexError) as error:
            raise APIError("llm_failed", "LLM request failed", 502) from error
        return {"answer": answer, "sources": sources}

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
