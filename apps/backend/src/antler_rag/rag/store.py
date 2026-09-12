from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import chromadb
import httpx
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import Settings

MAX_EMBEDDING_BATCH_SIZE = 10
logger = logging.getLogger("antler_rag")


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    filename: str
    content: str
    distance: float | None
    chunk_index: int


class OpenAICompatibleEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embed text through an OpenAI-compatible `/embeddings` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int | None = None,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        embeddings: Embeddings = []
        for start in range(0, len(input), MAX_EMBEDDING_BATCH_SIZE):
            embeddings.extend(self._embed_batch(input[start : start + MAX_EMBEDDING_BATCH_SIZE]))
        return embeddings

    def _embed_batch(self, input: Documents) -> Embeddings:
        payload: dict[str, Any] = {"model": self.model, "input": list(input)}
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        started = perf_counter()
        try:
            response = self.client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            status_code = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
            logger.warning("embedding_request_failed model=%s batch_size=%d status=%s error_type=%s duration_ms=%d", self.model, len(input), status_code, type(error).__name__, (perf_counter() - started) * 1000)
            raise
        logger.info("embedding_request_completed model=%s batch_size=%d status=%s duration_ms=%d", self.model, len(input), response.status_code, (perf_counter() - started) * 1000)
        data = response.json().get("data")
        if not isinstance(data, list) or len(data) != len(input):
            raise ValueError("Embedding provider returned an invalid response")
        try:
            ordered = sorted(data, key=lambda item: item["index"])
            return [item["embedding"] for item in ordered]
        except (KeyError, TypeError):
            raise ValueError("Embedding provider returned an invalid response") from None

    @staticmethod
    def name() -> str:
        return "openai_compatible"

    def default_space(self) -> Space:
        return "cosine"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> EmbeddingFunction[Documents]:
        # Chroma probes this method to determine whether the function is legacy.
        # The real client is always injected by RAGStore; do not persist its secret.
        return OpenAICompatibleEmbeddingFunction(
            base_url=str(config["base_url"]),
            api_key=os.environ.get("RAG_LLM_API_KEY", ""),
            model=str(config["model"]),
            dimensions=config.get("dimensions"),
        )

    def get_config(self) -> dict[str, Any]:
        # Never place the API key in Chroma's persistent collection metadata.
        return {"base_url": self.base_url, "model": self.model, "dimensions": self.dimensions}


class RAGStore:
    """One Chroma collection filtered only by knowledge base and document."""

    def __init__(self, settings: Settings):
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.embedding_function: EmbeddingFunction[Documents] | None = None
        if settings.embedding_model:
            if not settings.llm_base_url or not settings.llm_api_key:
                raise ValueError(
                    "RAG_LLM_BASE_URL and RAG_LLM_API_KEY are required when RAG_EMBEDDING_MODEL is set"
                )
            self.embedding_function = OpenAICompatibleEmbeddingFunction(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            )
        self.collection: Collection = self.client.get_or_create_collection(
            name=settings.embedding_collection,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": settings.embedding_model or "chroma_default",
                "embedding_dimensions": settings.embedding_dimensions or 0,
            },
            embedding_function=self.embedding_function,
        )

    def recreate_collection(self) -> None:
        """Delete and recreate only this embedding-space collection for a full reindex."""
        try:
            self.client.delete_collection(self.collection.name)
        except ValueError:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata=self.collection.metadata,
            embedding_function=self.embedding_function,
        )

    def close(self) -> None:
        if isinstance(self.embedding_function, OpenAICompatibleEmbeddingFunction):
            self.embedding_function.client.close()

    @staticmethod
    def _where(knowledge_base_id: str, document_ids: list[str] | None = None) -> dict:
        terms: list[dict] = [{"knowledge_base_id": knowledge_base_id}]
        if document_ids:
            terms.append({"document_id": document_ids[0]} if len(document_ids) == 1 else {"document_id": {"$in": document_ids}})
        return terms[0] if len(terms) == 1 else {"$and": terms}

    def index(self, *, knowledge_base_id: str, document_id: str, filename: str, text: str, chunk_size: int, chunk_overlap: int, digest: str) -> int:
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=["\n\n", "\n", "。", ". ", " ", ""])
        chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
        if not chunks:
            raise ValueError("The document did not contain extractable text.")
        self.collection.add(
            ids=[f"{document_id}:{index}" for index in range(len(chunks))],
            documents=chunks,
            metadatas=[{"knowledge_base_id": knowledge_base_id, "document_id": document_id, "filename": filename, "sha256": digest, "chunk_index": index} for index in range(len(chunks))],
        )
        return len(chunks)

    def retrieve(self, *, knowledge_base_id: str, query: str, top_k: int, document_ids: list[str] | None = None) -> list[RetrievedChunk]:
        result = self.collection.query(query_texts=[query], n_results=top_k, where=self._where(knowledge_base_id, document_ids), include=["documents", "metadatas", "distances"])
        return [RetrievedChunk(chunk_id=chunk_id, document_id=str(metadata["document_id"]), knowledge_base_id=str(metadata["knowledge_base_id"]), filename=str(metadata["filename"]), content=document, distance=distance, chunk_index=int(metadata["chunk_index"])) for chunk_id, document, metadata, distance in zip(result.get("ids", [[]])[0], result.get("documents", [[]])[0], result.get("metadatas", [[]])[0], result.get("distances", [[]])[0], strict=True)]

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        payload = self.collection.get(where=self._where(knowledge_base_id, [document_id]), include=[])
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        payload = self.collection.get(where=self._where(knowledge_base_id), include=[])
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def healthy(self) -> bool:
        self.collection.count()
        return True


def upload_path(root: Path, knowledge_base_id: str, stored_filename: str) -> Path:
    return root / knowledge_base_id / "uploads" / stored_filename
