from __future__ import annotations

import json
from typing import Annotated

from fastapi import Depends, Header, Request

from core.config import Settings
from db import Database
from models.schemas import Principal
from rag import RAGStore, RetrievalService
from rag.agentic import AgentService
from rag.graph_build import GraphBuildService
from rag.graph_store import GraphStore
from services.errors import APIError
from utils.security import ROLES, token_digest


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.db


def get_store(request: Request) -> RAGStore:
    return request.app.state.store


def get_retrieval(request: Request) -> RetrievalService:
    return request.app.state.retrieval


def get_agentic(request: Request) -> AgentService:
    return request.app.state.agentic


def get_graph_store(request: Request) -> GraphStore:
    return request.app.state.graph_store


def get_graph_build(request: Request) -> GraphBuildService:
    return request.app.state.graph_build


def session_principal(
    authorization: Annotated[str | None, Header()] = None,
    database: Database = Depends(get_database),
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
        role=user["role"],
        must_change_password=bool(user["must_change_password"]),
        session_id=user["session_id"],
    )


def normal_session(principal: Principal = Depends(session_principal)) -> Principal:
    if principal.must_change_password:
        raise APIError(
            "password_change_required", "Change the initial password before continuing", 403
        )
    if principal.role not in ROLES:
        raise APIError(
            "account_not_authorized", "This account has not been granted workspace access", 403
        )
    return principal


def access(required_scope: str | None = None, roles: set[str] | None = None):
    def dependency(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
        authorization: Annotated[str | None, Header()] = None,
        database: Database = Depends(get_database),
    ) -> Principal:
        if x_api_key:
            if not required_scope:
                raise APIError("insufficient_scope", "API keys cannot access this endpoint", 403)
            key = database.key_by_hash(token_digest(x_api_key))
            if not key:
                raise APIError("invalid_api_key", "API key is invalid, expired, or revoked", 401)
            scopes = set(json.loads(key["scopes_json"]))
            if required_scope not in scopes:
                raise APIError(
                    "insufficient_scope", "The API key does not grant this operation", 403
                )
            database.touch_key(key["id"])
            return Principal(
                actor_type="api_key", actor_id=key["id"], user_id=key["created_by"], scopes=scopes
            )
        if not authorization or not authorization.startswith("Bearer "):
            raise APIError("authentication_required", "Authentication is required", 401)
        user = database.session_user(token_digest(authorization.removeprefix("Bearer ").strip()))
        if not user:
            raise APIError("invalid_session", "Session is invalid or expired", 401)
        if user["must_change_password"]:
            raise APIError(
                "password_change_required", "Change the initial password before continuing", 403
            )
        if user["role"] not in ROLES:
            raise APIError(
                "account_not_authorized", "This account has not been granted workspace access", 403
            )
        if roles and user["role"] not in roles:
            raise APIError("forbidden", "You do not have permission for this operation", 403)
        return Principal(
            actor_type="user",
            actor_id=user["id"],
            user_id=user["id"],
            role=user["role"],
            session_id=user["session_id"],
        )

    return dependency


def administrator(principal: Principal = Depends(normal_session)) -> Principal:
    if principal.role != "admin":
        raise APIError("forbidden", "Administrator permission is required", 403)
    return principal


def audit(
    request: Request,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
) -> None:
    request.app.state.db.audit(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request.headers.get("x-request-id", "unknown"),
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
    )
