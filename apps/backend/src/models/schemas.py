from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class UserCreate(BaseModel):
    email: str
    role: Literal["admin", "editor", "viewer"]
    initial_password: str = Field(min_length=12, max_length=256)


class UserPatch(BaseModel):
    role: Literal["admin", "editor", "viewer"] | None = None
    status: Literal["active", "disabled"] | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["retrieve", "chat"])
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    chunk_size: int = Field(default=900, ge=100, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)


class KnowledgeBasePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class RetrieveRequest(BaseModel):
    knowledge_base_id: str
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None, max_length=100)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    rerank: bool = False


class ChatRequest(RetrieveRequest):
    """A chat request accepts both the new `message` and legacy `query` fields."""

    query: str = Field(
        min_length=1,
        max_length=10_000,
        validation_alias=AliasChoices("message", "query"),
    )
    system_prompt: str | None = Field(default=None, max_length=5000)


class AgenticRagRequest(BaseModel):
    knowledge_base_id: str
    message: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["auto", "vector", "keyword", "graph", "hybrid"] = "auto"
    include_trace: bool = False


class GraphRebuildRequest(BaseModel):
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    all_documents: bool = False

    @model_validator(mode="after")
    def select_documents_once(self) -> GraphRebuildRequest:
        if bool(self.document_ids) == self.all_documents:
            raise ValueError("Specify exactly one of document_ids or all_documents=true")
        if self.document_ids and len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must be unique")
        return self


class GraphSearchRequest(BaseModel):
    knowledge_base_id: str
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] | None = Field(default=None, max_length=100)
    max_hops: Literal[1, 2] = 1


class Principal(BaseModel):
    actor_type: Literal["user", "api_key"]
    actor_id: str
    user_id: str | None = None
    role: str | None = None
    must_change_password: bool = False
    session_id: str | None = None
    scopes: set[str] = Field(default_factory=set)
