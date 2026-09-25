from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from core.config import Settings
from db import Database
from models.schemas import AgenticRagRequest, Principal, RetrieveRequest
from rag.agentic import AgentService
from routers.dependencies import access, audit, get_agentic, get_database, get_settings
from routers.retrieval import validate_retrieve
from services.errors import APIError
from utils.security import ROLES, chunk_payload

router = APIRouter(prefix="/api/v1", tags=["agentic retrieval"])


@router.post("/agentic-rag")
async def agentic_rag(
    payload: AgenticRagRequest,
    request: Request,
    principal: Principal = Depends(access("agentic:query", ROLES)),
    database: Database = Depends(get_database),
    agent: AgentService = Depends(get_agentic),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
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
