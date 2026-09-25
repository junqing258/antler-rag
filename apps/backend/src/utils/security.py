from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pwdlib import PasswordHash

from rag import Evidence, RetrievedChunk

password_hash = PasswordHash.recommended()
ROLES = {"admin", "editor", "viewer"}
WRITE_ROLES = {"admin", "editor"}
SCOPES = {
    "kb:read",
    "retrieve",
    "chat",
    "documents:read",
    "documents:write",
    "documents:delete",
    "agentic:query",
    "graph:read",
}


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_request_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid4().hex[:8]}"


def expiry(hours: int) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "email", "status", "role", "must_change_password", "created_at")
    return {key: user[key] for key in fields if key in user}


def public_key(key: dict[str, Any]) -> dict[str, Any]:
    item = {name: value for name, value in key.items() if name != "key_hash"}
    item["scopes"] = json.loads(item.pop("scopes_json"))
    return item


def chunk_payload(chunk: RetrievedChunk | Evidence) -> dict[str, str | float | int | None]:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "knowledge_base_id": chunk.knowledge_base_id,
        "filename": chunk.filename,
        "content": chunk.content,
        "distance": chunk.distance,
        "chunk_index": chunk.chunk_index,
        "rerank_score": chunk.rerank_score,
    }
