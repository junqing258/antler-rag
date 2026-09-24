from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import chromadb
import httpx
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import Settings

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
    rerank_score: float | None = None


@dataclass(frozen=True)
class IndexedChunk:
    """The exact text and ID accepted by Chroma during document indexing."""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    chunk_index: int
    content: str


class RerankerError(RuntimeError):
    """Raised when a requested reranker cannot be used."""


class Reranker(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class TEIReranker:
    """CrossEncoder reranking through Hugging Face Text Embeddings Inference's /rerank API."""

    def __init__(self, *, base_url: str, api_key: str | None = None, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))

    def close(self) -> None:
        self.client.close()

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = perf_counter()
        try:
            response = self.client.post(f"{self.base_url}/rerank", headers=headers,
                                        json={"query": query, "texts": list(documents)})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("reranker_request_failed candidates=%d error_type=%s duration_ms=%d", len(documents), type(error).__name__, (perf_counter() - started) * 1000)
            raise RerankerError("Reranker request failed") from error
        if not isinstance(payload, list):
            raise RerankerError("Reranker returned an invalid response")
        scores: list[float | None] = [None] * len(documents)
        try:
            for item in payload:
                index = item["index"]
                if not isinstance(index, int) or not 0 <= index < len(documents):
                    raise ValueError
                scores[index] = float(item["score"])
        except (KeyError, TypeError, ValueError) as error:
            raise RerankerError("Reranker returned an invalid response") from error
        if any(score is None for score in scores):
            raise RerankerError("Reranker returned an incomplete response")
        return [float(score) for score in scores]


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
        self.reranker: Reranker | None = TEIReranker(base_url=settings.reranker_base_url,
                                                      api_key=settings.reranker_api_key) if settings.reranker_base_url else None
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
        if isinstance(self.reranker, TEIReranker):
            self.reranker.close()

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

    @staticmethod
    def similarity_score(distance: float | None) -> float:
        """Map Chroma cosine distance to cosine similarity, clamped to the UI's 0–1 range."""
        if distance is None:
            return 0.0
        return max(0.0, min(1.0, 1.0 - distance))

    def retrieve(self, *, knowledge_base_id: str, query: str, top_k: int, document_ids: list[str] | None = None, score_threshold: float | None = None, rerank: bool = False) -> list[RetrievedChunk]:
        if rerank and self.reranker is None:
            raise RerankerError("Reranking is not configured. Set RAG_RERANKER_BASE_URL before enabling rerank.")
        # A CrossEncoder needs a larger candidate set to improve the final top-k order.
        candidate_count = min(100, top_k * 4) if rerank else top_k
        result = self.collection.query(query_texts=[query], n_results=candidate_count, where=self._where(knowledge_base_id, document_ids), include=["documents", "metadatas", "distances"])
        chunks = [RetrievedChunk(chunk_id=chunk_id, document_id=str(metadata["document_id"]), knowledge_base_id=str(metadata["knowledge_base_id"]), filename=str(metadata["filename"]), content=document, distance=distance, chunk_index=int(metadata["chunk_index"])) for chunk_id, document, metadata, distance in zip(result.get("ids", [[]])[0], result.get("documents", [[]])[0], result.get("metadatas", [[]])[0], result.get("distances", [[]])[0], strict=True)]
        if score_threshold is not None:
            chunks = [chunk for chunk in chunks if self.similarity_score(chunk.distance) >= score_threshold]
        if rerank and chunks:
            assert self.reranker is not None
            scores = self.reranker.score(query, [chunk.content for chunk in chunks])
            chunks = [replace(chunk, rerank_score=score) for chunk, score in zip(chunks, scores, strict=True)]
            chunks.sort(key=lambda chunk: chunk.rerank_score if chunk.rerank_score is not None else float("-inf"), reverse=True)
        return chunks[:top_k]

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        payload = self.collection.get(where=self._where(knowledge_base_id, [document_id]), include=[])
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def document_chunks(self, knowledge_base_id: str, document_id: str) -> list[IndexedChunk]:
        """Read the public Chroma records, never re-chunking source content."""
        payload = self.collection.get(
            where=self._where(knowledge_base_id, [document_id]),
            include=["documents", "metadatas"],
        )
        chunks = [
            IndexedChunk(
                chunk_id=chunk_id,
                document_id=str(metadata["document_id"]),
                knowledge_base_id=str(metadata["knowledge_base_id"]),
                chunk_index=int(metadata["chunk_index"]),
                content=content,
            )
            for chunk_id, content, metadata in zip(
                payload.get("ids", []), payload.get("documents", []), payload.get("metadatas", []), strict=True
            )
        ]
        return sorted(chunks, key=lambda chunk: chunk.chunk_index)

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        payload = self.collection.get(where=self._where(knowledge_base_id), include=[])
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def healthy(self) -> bool:
        self.collection.count()
        return True


def upload_path(root: Path, knowledge_base_id: str, stored_filename: str) -> Path:
    return root / knowledge_base_id / "uploads" / stored_filename
