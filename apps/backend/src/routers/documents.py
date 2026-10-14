from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from core.config import Settings
from db import Database
from models.schemas import Principal
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
from services.document_indexing import DocumentIndexingService
from services.errors import APIError
from utils.documents import UnsupportedDocument
from utils.logging import configure_logging
from utils.security import ROLES, WRITE_ROLES, chunk_payload

logger = configure_logging()
router = APIRouter(
    prefix="/api/v1/knowledge-bases/{knowledge_base_id}/documents", tags=["documents"]
)


@router.get("")
def list_documents(
    knowledge_base_id: str,
    _: Principal = Depends(access("documents:read", ROLES)),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    if not database.knowledge_base(knowledge_base_id, True):
        raise APIError("not_found", "Knowledge base was not found", 404)
    return {"items": database.documents(knowledge_base_id)}


@router.post("", status_code=201)
async def upload_documents(
    knowledge_base_id: str,
    files: Annotated[list[UploadFile], File()],
    request: Request,
    principal: Principal = Depends(access("documents:write", WRITE_ROLES)),
    database: Database = Depends(get_database),
    rag: RAGStore = Depends(get_store),
    graph: GraphStore = Depends(get_graph_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    kb = database.knowledge_base(knowledge_base_id, True)
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
        try:
            if len(content) > settings.max_upload_bytes:
                raise APIError("file_too_large", f"Each file must be at most {settings.max_upload_bytes} bytes", 413)
            document = DocumentIndexingService(database, rag, graph, settings).upload(
                kb, filename=filename, content=content, created_by=principal.user_id or "",
            )
            indexed.append(document)
            audit(request, principal, "create", "document", document["id"])
            logger.info("document_index_completed request_id={request_id} document_id={document_id} chunk_count={chunk_count}",
                        request_id=request.state.request_id, document_id=document["id"], chunk_count=document["chunk_count"])
        except APIError:
            raise
        except (UnsupportedDocument, ValueError) as error:
            raise APIError("invalid_document", str(error), 422) from error
        except Exception as error:
            logger.exception("document_index_failed request_id={request_id}", request_id=request.state.request_id)
            raise APIError("indexing_failed", "Document indexing failed", 500) from error
        finally:
            await upload.close()
    return {"documents": indexed}


@router.get("/{document_id}")
def get_document(
    knowledge_base_id: str,
    document_id: str,
    _: Principal = Depends(access("documents:read", ROLES)),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    document = database.document(knowledge_base_id, document_id)
    if not document:
        raise APIError("not_found", "Document was not found", 404)
    return document


@router.get("/{document_id}/chunks")
def get_document_chunks(
    knowledge_base_id: str, document_id: str,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
    _: Principal = Depends(access("documents:read", ROLES)),
    database: Database = Depends(get_database), rag: RAGStore = Depends(get_store),
) -> dict[str, Any]:
    if not database.knowledge_base(knowledge_base_id, True):
        raise APIError("not_found", "Knowledge base was not found", 404)
    document = database.document(knowledge_base_id, document_id)
    if not document or document["status"] == "deleted":
        raise APIError("not_found", "Document was not found", 404)
    if document["status"] != "ready":
        return {"items": [], "total": 0}
    chunks = rag.document_chunks(knowledge_base_id, document_id)
    return {"items": [chunk_payload(chunk) for chunk in chunks[offset:offset + limit]], "total": len(chunks)}


@router.delete("/{document_id}", status_code=204)
def delete_document(
    knowledge_base_id: str,
    document_id: str,
    request: Request,
    principal: Principal = Depends(access("documents:delete", WRITE_ROLES)),
    database: Database = Depends(get_database),
    rag: RAGStore = Depends(get_store),
    graph: GraphStore = Depends(get_graph_store),
    settings: Settings = Depends(get_settings),
) -> None:
    document = database.document(knowledge_base_id, document_id)
    if not document:
        raise APIError("not_found", "Document was not found", 404)
    database.set_document_status(knowledge_base_id, document_id, "deleting")
    try:
        graph.cleanup_document(knowledge_base_id=knowledge_base_id, document_id=document_id)
        rag.delete_document(knowledge_base_id, document_id)
        upload_path(settings.uploads_dir, knowledge_base_id, document["stored_filename"]).unlink(
            missing_ok=True
        )
        database.delete_document_record(knowledge_base_id, document_id)
    except Exception as error:
        database.set_document_status(knowledge_base_id, document_id, "delete_failed")
        raise APIError(
            "delete_failed", "Document cleanup failed and can be retried", 500
        ) from error
    audit(request, principal, "delete", "document", document_id)
