from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from core.config import Settings
from db import Database
from models.schemas import ChatRequest, Principal, RetrieveRequest
from rag import RetrievalService
from rag.store import RerankerError
from routers.dependencies import access, get_database, get_retrieval, get_settings
from services.chat import generate_answer
from services.errors import APIError
from utils.logging import configure_logging
from utils.security import ROLES, chunk_payload

logger = configure_logging()
router = APIRouter(prefix="/api/v1", tags=["retrieval"])


def validate_retrieve(payload: RetrieveRequest, database: Database) -> None:
    if not database.knowledge_base(payload.knowledge_base_id, True):
        raise APIError("not_found", "Knowledge base was not found", 404)
    for document_id in payload.document_ids or []:
        if not database.document(payload.knowledge_base_id, document_id):
            raise APIError("not_found", "Document was not found", 404)


@router.post("/retrieve")
def retrieve(
    payload: RetrieveRequest,
    _: Principal = Depends(access("retrieve", ROLES)),
    database: Database = Depends(get_database),
    service: RetrievalService = Depends(get_retrieval),
) -> dict[str, Any]:
    validate_retrieve(payload, database)
    try:
        chunks = service.retrieve(
            knowledge_base_id=payload.knowledge_base_id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
            score_threshold=payload.score_threshold,
            rerank=payload.rerank,
        )
    except RerankerError as error:
        raise APIError("reranker_unavailable", str(error), 503) from error
    return {"results": [chunk_payload(chunk) for chunk in chunks]}


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    _: Principal = Depends(access("chat", ROLES)),
    database: Database = Depends(get_database),
    service: RetrievalService = Depends(get_retrieval),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    validate_retrieve(payload, database)
    try:
        chunks = service.retrieve(
            knowledge_base_id=payload.knowledge_base_id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
            score_threshold=payload.score_threshold,
            rerank=payload.rerank,
        )
    except RerankerError as error:
        raise APIError("reranker_unavailable", str(error), 503) from error
    sources = [chunk_payload(chunk) for chunk in chunks]
    if not settings.llm_base_url or not settings.chat_model:
        return {
            "answer": None,
            "sources": sources,
            "detail": "LLM is not configured; use sources as Agent context.",
        }
    prompt = (
        payload.system_prompt
        or "Answer only from the provided sources. If they do not answer the question, say so and cite source numbers."
    )
    answer = await generate_answer(
        settings=settings,
        prompt=prompt,
        question=payload.query,
        chunks=chunks,
        request_id=request.state.request_id,
        logger=logger,
    )
    return {"answer": answer, "sources": sources}
