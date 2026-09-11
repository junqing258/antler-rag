from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


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
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

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
    def tenants_dir(self) -> Path:
        return self.data_dir / "tenants"
