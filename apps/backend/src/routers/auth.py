from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request

from core.config import Settings
from db import Database
from db.repository import now
from models.schemas import ChangePasswordRequest, LoginRequest, Principal
from routers.dependencies import audit, get_database, get_settings, session_principal
from services.errors import APIError
from utils.security import ROLES, expiry, password_hash, public_user, token_digest

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
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
            "The initial password has expired; ask an administrator to reset it",
            403,
        )
    if user["role"] not in ROLES:
        raise APIError(
            "account_not_authorized", "This account has not been granted workspace access", 403
        )
    token = secrets.token_urlsafe(32)
    database.create_session(user["id"], token_digest(token), expiry(settings.session_hours))
    database.audit(
        action="login",
        resource_type="session",
        request_id=request.headers.get("x-request-id", "unknown"),
        actor_type="user",
        actor_id=user["id"],
    )
    return {"token": token, "user": public_user(user)}


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    principal: Principal = Depends(session_principal),
    database: Database = Depends(get_database),
) -> None:
    database.revoke_session(principal.session_id or "")
    audit(request, principal, "logout", "session")


@router.get("/me")
def me(
    principal: Principal = Depends(session_principal), database: Database = Depends(get_database)
) -> dict[str, Any]:
    return {
        "user": public_user(database.user(principal.user_id or "") or {}),
        "must_change_password": principal.must_change_password,
    }


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(session_principal),
    database: Database = Depends(get_database),
) -> None:
    user = database.user(principal.user_id or "")
    if not user or not password_hash.verify(payload.current_password, user["password_hash"]):
        raise APIError("invalid_credentials", "Current password is incorrect", 401)
    database.change_password(user["id"], password_hash.hash(payload.new_password))
    database.revoke_user_sessions(user["id"])
    audit(request, principal, "change_password", "user", user["id"])
