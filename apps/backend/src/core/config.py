from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_repository_env_file(source_file: Path) -> Path | None:
    """Find a development `.env` without assuming a fixed source-tree depth."""
    for parent in source_file.resolve().parents:
        env_file = parent / ".env"
        if env_file.is_file():
            return env_file
    return None


REPOSITORY_ENV_FILE = find_repository_env_file(Path(__file__))


class Settings(BaseSettings):
    """Runtime settings. Secrets are accepted only through environment variables."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="RAG_",
        extra="ignore",
    )

    environment: str = "development"
    data_dir: Path = Path("data")
    collection: str = "rag_chunks"
    chunk_size: int = Field(default=900, ge=100, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_files_per_request: int = Field(default=10, ge=1, le=100)
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    api_key_days: int = Field(default=90, ge=1, le=3650)
    bootstrap_admin_email: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, ge=1, le=4096)
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    agentic_enabled: bool = True
    agent_max_steps: int = Field(default=6, ge=4, le=12)
    agent_max_subqueries: int = Field(default=3, ge=1, le=6)
    agent_max_llm_calls: int = Field(default=5, ge=2, le=10)
    agent_timeout_seconds: int = Field(default=30, ge=1, le=120)
    graph_enabled: bool = True
    graph_extractor_model: str | None = None
    graph_extractor_version: str = Field(default="v1", min_length=1, max_length=80)
    graph_min_confidence: float = Field(default=0.7, ge=0, le=1)
    graph_max_chunks_per_document: int = Field(default=20, ge=1, le=200)
    graph_rebuild_max_documents: int = Field(default=10, ge=1, le=50)
    graph_rebuild_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_bootstrap(self) -> Settings:
        if bool(self.supabase_url) != bool(self.supabase_publishable_key):
            raise ValueError("Set both RAG_SUPABASE_URL and RAG_SUPABASE_PUBLISHABLE_KEY")
        key = self.supabase_publishable_key
        if key.startswith("sb_secret_"):
            raise ValueError("Use a Supabase publishable key, never a secret key")
        if key.count(".") == 2:
            try:
                part = key.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid Supabase public key") from error
            if claims.get("role") != "anon":
                raise ValueError("Only a public anon JWT may be exposed to the frontend")
        return self

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def embedding_collection(self) -> str:
        fingerprint = "\0".join(
            (
                self.llm_base_url or "",
                self.embedding_model or "",
                str(self.embedding_dimensions or "default"),
            )
        )
        if not self.embedding_model:
            return self.collection
        return f"{self.collection}-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12]}"
