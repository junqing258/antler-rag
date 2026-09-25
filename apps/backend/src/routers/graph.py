from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.config import Settings
from db import Database
from models.schemas import GraphRebuildRequest, GraphSearchRequest, Principal, RetrieveRequest
from rag.graph_build import GraphBuildService
from rag.graph_store import GraphStore
from routers.dependencies import (
    access,
    administrator,
    audit,
    get_database,
    get_graph_build,
    get_graph_store,
    get_settings,
)
from routers.retrieval import validate_retrieve
from services.errors import APIError
from utils.security import ROLES

router = APIRouter(prefix="/api/v1", tags=["knowledge graph"])


@router.post("/knowledge-bases/{knowledge_base_id}/graph/rebuild")
async def rebuild_graph(
    knowledge_base_id: str,
    payload: GraphRebuildRequest,
    request: Request,
    principal: Principal = Depends(administrator),
    database: Database = Depends(get_database),
    builder: GraphBuildService = Depends(get_graph_build),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if not settings.graph_enabled:
        raise APIError("feature_disabled", "Graph retrieval is disabled", 503)
    if not database.knowledge_base(knowledge_base_id, True):
        raise APIError("not_found", "Knowledge base was not found", 404)
    document_ids = (
        [item["id"] for item in database.documents(knowledge_base_id) if item["status"] == "ready"]
        if payload.all_documents
        else payload.document_ids or []
    )
    if len(document_ids) > settings.graph_rebuild_max_documents:
        raise APIError("rebuild_limit_exceeded", "Too many documents selected", 422)
    for document_id in document_ids:
        if not database.document(knowledge_base_id, document_id):
            raise APIError("not_found", "Document was not found", 404)
    try:
        result = await builder.rebuild(
            knowledge_base_id=knowledge_base_id,
            document_ids=document_ids,
            requested_by=principal.user_id,
        )
    except ValueError as error:
        raise APIError("graph_not_configured", str(error), 503) from error
    audit(request, principal, "graph_rebuild", "knowledge_base", knowledge_base_id)
    return result


@router.get("/knowledge-bases/{knowledge_base_id}/graph/status")
def graph_status(
    knowledge_base_id: str,
    _: Principal = Depends(access("graph:read", ROLES)),
    database: Database = Depends(get_database),
    graph: GraphStore = Depends(get_graph_store),
) -> dict[str, object]:
    if not database.knowledge_base(knowledge_base_id, True):
        raise APIError("not_found", "Knowledge base was not found", 404)
    return {"documents": graph.document_states(knowledge_base_id)}


@router.post("/graph/search")
def graph_search(
    payload: GraphSearchRequest,
    _: Principal = Depends(access("graph:read", ROLES)),
    database: Database = Depends(get_database),
    graph: GraphStore = Depends(get_graph_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    validate_retrieve(
        RetrieveRequest(
            knowledge_base_id=payload.knowledge_base_id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        ),
        database,
    )
    if not settings.graph_enabled:
        raise APIError("feature_disabled", "Graph retrieval is disabled", 503)
    rows = graph.search(
        knowledge_base_id=payload.knowledge_base_id, query=payload.query, top_k=payload.top_k
    )
    return {
        "results": [
            {
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "knowledge_base_id": payload.knowledge_base_id,
                "content": f"{row['subject']} {row['predicate']} {row['object']}",
                "source_type": "graph",
                "score": row["confidence"],
                "graph_path": [row["subject"], row["predicate"], row["object"]],
            }
            for row in rows
        ]
    }
