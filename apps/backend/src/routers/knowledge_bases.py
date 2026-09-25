from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from core.config import Settings
from db import Database
from models.schemas import KnowledgeBaseCreate, KnowledgeBasePatch, Principal
from rag import RAGStore
from rag.graph_store import GraphStore
from rag.store import upload_path
from routers.dependencies import (
    access,
    audit,
    get_database,
    get_graph_store,
    get_settings,
    get_store,
)
from services.errors import APIError
from utils.security import ROLES, WRITE_ROLES

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge bases"])


@router.get("")
def list_knowledge_bases(
    _: Principal = Depends(access("kb:read", ROLES)), database: Database = Depends(get_database)
) -> dict[str, Any]:
    return {"items": database.knowledge_bases()}


@router.post("", status_code=201)
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    request: Request,
    principal: Principal = Depends(access(roles=WRITE_ROLES)),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    if payload.chunk_overlap >= payload.chunk_size:
        raise APIError("validation_error", "chunk_overlap must be smaller than chunk_size", 422)
    try:
        kb = database.create_knowledge_base(
            payload.name, payload.description, payload.chunk_size, payload.chunk_overlap
        )
    except Exception as error:
        raise APIError("conflict", "A knowledge base with this name already exists", 409) from error
    audit(request, principal, "create", "knowledge_base", kb["id"])
    return kb


@router.get("/{knowledge_base_id}")
def get_knowledge_base(
    knowledge_base_id: str,
    _: Principal = Depends(access(roles=ROLES)),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    kb = database.knowledge_base(knowledge_base_id, True)
    if not kb:
        raise APIError("not_found", "Knowledge base was not found", 404)
    return kb


@router.patch("/{knowledge_base_id}")
def patch_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBasePatch,
    request: Request,
    principal: Principal = Depends(access(roles=WRITE_ROLES)),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    if not database.update_knowledge_base(knowledge_base_id, payload.name, payload.description):
        raise APIError("not_found", "Knowledge base was not found", 404)
    audit(request, principal, "update", "knowledge_base", knowledge_base_id)
    return database.knowledge_base(knowledge_base_id) or {}


@router.delete("/{knowledge_base_id}", status_code=202)
def delete_knowledge_base(
    knowledge_base_id: str,
    request: Request,
    principal: Principal = Depends(access(roles=WRITE_ROLES)),
    database: Database = Depends(get_database),
    rag: RAGStore = Depends(get_store),
    graph: GraphStore = Depends(get_graph_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not database.knowledge_base(knowledge_base_id):
        raise APIError("not_found", "Knowledge base was not found", 404)
    database.set_knowledge_base_status(knowledge_base_id, "deleting")
    try:
        for document in database.documents(knowledge_base_id):
            graph.cleanup_document(knowledge_base_id=knowledge_base_id, document_id=document["id"])
            rag.delete_document(knowledge_base_id, document["id"])
            upload_path(
                settings.uploads_dir, knowledge_base_id, document["stored_filename"]
            ).unlink(missing_ok=True)
            database.delete_document_record(knowledge_base_id, document["id"])
        rag.delete_knowledge_base(knowledge_base_id)
        database.set_knowledge_base_status(knowledge_base_id, "deleted")
    except Exception as error:
        database.set_knowledge_base_status(knowledge_base_id, "delete_failed")
        raise APIError(
            "delete_failed", "Knowledge base cleanup failed and can be retried", 500
        ) from error
    audit(request, principal, "delete", "knowledge_base", knowledge_base_id)
    return {"status": "deleted"}
