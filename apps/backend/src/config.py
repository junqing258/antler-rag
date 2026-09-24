from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_repository_env_file(source_file: Path) -> Path | None:
    """Find a development `.env` without assuming a fixed source-tree depth.

    Production containers receive configuration through their process environment,
    so they intentionally return ``None`` when no `.env` is present.
    """
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
    session_hours: int = Field(default=12, ge=1, le=168)
    temporary_password_hours: int = Field(default=24, ge=1, le=168)
    api_key_days: int = Field(default=90, ge=1, le=3650)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    # The OpenAI-compatible provider is shared by chat and embeddings. Models are
    # deliberately separate because an embedding model cannot serve /chat/completions.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, ge=1, le=4096)
    # URL of a Hugging Face Text Embeddings Inference service exposing POST /rerank.
    # Leave unset to keep the lightweight vector-only deployment.
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    agentic_enabled: bool = False
    agent_max_steps: int = Field(default=6, ge=4, le=12)
    agent_max_subqueries: int = Field(default=3, ge=1, le=6)
    agent_max_llm_calls: int = Field(default=5, ge=2, le=10)
    agent_timeout_seconds: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_bootstrap(self) -> Settings:
        if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
            raise ValueError(
                "Set both RAG_BOOTSTRAP_ADMIN_EMAIL and RAG_BOOTSTRAP_ADMIN_PASSWORD together"
            )
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
        """Keep vector spaces from different providers/models out of one collection."""
        if not self.embedding_model:
            return self.collection
        fingerprint = "\0".join(
            (
                self.llm_base_url or "",
                self.embedding_model,
                str(self.embedding_dimensions or "default"),
            )
        )
        return f"{self.collection}-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12]}"
