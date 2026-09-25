from fastapi import APIRouter, Depends

from core.config import Settings
from models.schemas import Principal
from rag import RAGStore
from routers.dependencies import access, get_database, get_settings, get_store
from utils.security import ROLES

router = APIRouter(tags=["system"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(database=Depends(get_database), rag: RAGStore = Depends(get_store)) -> dict[str, str]:
    database.one("SELECT 1")
    rag.healthy()
    return {"status": "ok"}


@router.get("/api/v1/features")
def features(
    _: Principal = Depends(access("retrieve", ROLES)), settings: Settings = Depends(get_settings)
) -> dict[str, object]:
    graph_ready = bool(settings.graph_extractor_model and settings.llm_base_url)
    agent_ready = bool(settings.llm_base_url and settings.chat_model)
    return {
        "modes": {
            "vector": {"enabled": True, "ready": True, "reason": None},
            "keyword": {"enabled": False, "ready": False, "reason": "feature_disabled"},
            "graph": {
                "enabled": settings.graph_enabled,
                "ready": graph_ready,
                "reason": None
                if settings.graph_enabled and graph_ready
                else ("not_configured" if settings.graph_enabled else "feature_disabled"),
            },
            "hybrid": {"enabled": False, "ready": False, "reason": "feature_disabled"},
            "agentic": {
                "enabled": settings.agentic_enabled,
                "ready": agent_ready,
                "reason": None
                if settings.agentic_enabled and agent_ready
                else ("not_configured" if settings.agentic_enabled else "feature_disabled"),
            },
        }
    }
