from typing import Any

from fastapi import APIRouter, Depends

from core.config import Settings
from db import Database
from models.schemas import Principal
from routers.dependencies import get_database, get_settings, session_principal
from services.errors import APIError
from utils.security import public_user

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.get("/config")
def config(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise APIError("auth_unavailable", "Supabase authentication is not configured", 503)
    return {"url": settings.supabase_url, "publishableKey": settings.supabase_publishable_key}


@router.get("/me")
def me(
    principal: Principal = Depends(session_principal), database: Database = Depends(get_database)
) -> dict[str, Any]:
    return {"user": public_user(database.user(principal.user_id or "") or {})}
