from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request

from core.config import Settings
from db import Database
from models.schemas import ApiKeyCreate, Principal, UserCreate, UserPatch
from routers.dependencies import administrator, audit, get_database, get_settings
from services.errors import APIError
from utils.security import SCOPES, expiry, password_hash, public_key, public_user, token_digest

router = APIRouter(prefix="/api/v1", tags=["administration"])


@router.get("/users")
def list_users(
    _: Principal = Depends(administrator), database: Database = Depends(get_database)
) -> dict[str, Any]:
    return {"items": database.users()}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    principal: Principal = Depends(administrator),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        user = database.create_user(
            payload.email,
            password_hash.hash(payload.initial_password),
            payload.role,
            expiry(settings.temporary_password_hours),
        )
    except Exception as error:
        raise APIError("conflict", "A user with this email already exists", 409) from error
    audit(request, principal, "create", "user", user["id"])
    return public_user(user)


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    payload: UserPatch,
    request: Request,
    principal: Principal = Depends(administrator),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    try:
        changed = database.update_user(user_id, payload.role, payload.status)
    except ValueError as error:
        raise APIError("last_active_admin", str(error), 409) from error
    if not changed:
        raise APIError("not_found", "User was not found", 404)
    audit(request, principal, "update", "user", user_id)
    return public_user(database.user(user_id) or {})


@router.get("/api-keys")
def list_api_keys(
    _: Principal = Depends(administrator), database: Database = Depends(get_database)
) -> dict[str, Any]:
    return {"items": [public_key(key) for key in database.list_api_keys()]}


@router.post("/api-keys", status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    principal: Principal = Depends(administrator),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    if not set(payload.scopes).issubset(SCOPES) or not payload.scopes:
        raise APIError("validation_error", "Unknown or empty API key scopes", 422)
    raw = f"ark_{secrets.token_urlsafe(32)}"
    key = database.create_api_key(
        payload.name,
        raw[:12],
        token_digest(raw),
        sorted(set(payload.scopes)),
        expiry(payload.expires_in_days * 24) if payload.expires_in_days else None,
        principal.user_id or "",
    )
    audit(request, principal, "create", "api_key", key["id"])
    return {**public_key(key), "api_key": raw}


@router.delete("/api-keys/{key_id}", status_code=204)
def delete_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(administrator),
    database: Database = Depends(get_database),
) -> None:
    if not database.revoke_api_key(key_id):
        raise APIError("not_found", "API key was not found", 404)
    audit(request, principal, "revoke", "api_key", key_id)
