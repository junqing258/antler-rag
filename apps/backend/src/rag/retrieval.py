"""Retrieval orchestration with a stable, source-neutral evidence model.

The vector store remains the only enabled retriever for now.  Keeping its adapter
behind this small service lets keyword and graph retrieval be added later without
changing the legacy HTTP contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Protocol

from .store import RAGStore, RetrievedChunk


@dataclass(frozen=True)
class Evidence:
    """A retriever result with a stable ID and enough provenance to cite it."""

    evidence_id: str
    knowledge_base_id: str
    document_id: str
    chunk_id: str
    chunk_index: int
    filename: str
    content: str
    source_type: Literal["vector", "keyword", "graph"]
    score: float | None
    distance: float | None = None
    rerank_score: float | None = None
    graph_path: tuple[str, ...] | None = None

    @classmethod
    def from_vector(cls, chunk: RetrievedChunk) -> Evidence:
        return cls(
            evidence_id=f"vector:{chunk.chunk_id}",
            knowledge_base_id=chunk.knowledge_base_id,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            filename=chunk.filename,
            content=chunk.content,
            source_type="vector",
            score=chunk.rerank_score
            if chunk.rerank_score is not None
            else RAGStore.similarity_score(chunk.distance),
            distance=chunk.distance,
            rerank_score=chunk.rerank_score,
        )


@dataclass(frozen=True)
class RetrievalFilters:
    knowledge_base_id: str
    top_k: int
    document_ids: tuple[str, ...] = ()
    score_threshold: float | None = None
    rerank: bool = False

    @classmethod
    def create(
        cls,
        *,
        knowledge_base_id: str,
        top_k: int,
        document_ids: list[str] | None = None,
        score_threshold: float | None = None,
        rerank: bool = False,
    ) -> RetrievalFilters:
        # The route performs existence and KB-ownership checks.  De-duplicating
        # here makes downstream retrievers deterministic without widening scope.
        return cls(
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
            document_ids=tuple(dict.fromkeys(document_ids or [])),
            score_threshold=score_threshold,
            rerank=rerank,
        )


@dataclass(frozen=True)
class RetrievalTrace:
    mode: str
    retrievers: tuple[str, ...]
    candidate_count: int
    result_count: int
    duration_ms: int


class Retriever(Protocol):
    name: str

    def retrieve(self, *, query: str, filters: RetrievalFilters) -> list[Evidence]: ...


class VectorRetriever:
    name = "vector"

    def __init__(self, store: RAGStore):
        self.store = store

    def retrieve(self, *, query: str, filters: RetrievalFilters) -> list[Evidence]:
        chunks = self.store.retrieve(
            knowledge_base_id=filters.knowledge_base_id,
            query=query,
            top_k=filters.top_k,
            document_ids=list(filters.document_ids) or None,
            score_threshold=filters.score_threshold,
            rerank=filters.rerank,
        )
        return [Evidence.from_vector(chunk) for chunk in chunks]


class RetrievalService:
    """Coordinates enabled retrievers while preserving vector-only semantics."""

    def __init__(self, vector_retriever: Retriever):
        self.vector_retriever = vector_retriever

    @classmethod
    def from_store(cls, store: RAGStore) -> RetrievalService:
        return cls(VectorRetriever(store))

    def search(
        self, *, query: str, filters: RetrievalFilters
    ) -> tuple[list[Evidence], RetrievalTrace]:
        started = perf_counter()
        candidates = self.vector_retriever.retrieve(query=query, filters=filters)
        # A future hybrid merger uses the same rule: one item per provenance chunk.
        evidence = self._deduplicate(candidates)[: filters.top_k]
        trace = RetrievalTrace(
            mode="vector",
            retrievers=(self.vector_retriever.name,),
            candidate_count=len(candidates),
            result_count=len(evidence),
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return evidence, trace

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
        score_threshold: float | None = None,
        rerank: bool = False,
    ) -> list[Evidence]:
        evidence, _ = self.search(
            query=query,
            filters=RetrievalFilters.create(
                knowledge_base_id=knowledge_base_id,
                top_k=top_k,
                document_ids=document_ids,
                score_threshold=score_threshold,
                rerank=rerank,
            ),
        )
        return evidence

    @staticmethod
    def _deduplicate(candidates: list[Evidence]) -> list[Evidence]:
        seen: set[str] = set()
        return [
            item for item in candidates if not (item.chunk_id in seen or seen.add(item.chunk_id))
        ]
