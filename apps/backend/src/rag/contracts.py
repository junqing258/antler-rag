"""与框架无关的索引与检索领域契约。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from rag.chunking import ChunkDraft, ChunkMetadata, ChunkStrategy


@dataclass(frozen=True)
class RetrievedChunk(ChunkMetadata):
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    filename: str
    content: str
    distance: float | None
    chunk_index: int
    rerank_score: float | None = None


@dataclass(frozen=True)
class IndexedChunk(ChunkMetadata):
    """文档索引时 Chroma 接受的精确文本与 ID。"""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    chunk_index: int
    content: str
    filename: str


@dataclass(frozen=True)
class Evidence(ChunkMetadata):
    """检索结果，带稳定 ID 与足够的溯源信息以供引用。"""

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
            else (max(0.0, min(1.0, 1.0 - chunk.distance)) if chunk.distance is not None else 0.0),
            distance=chunk.distance,
            rerank_score=chunk.rerank_score,
            **chunk.structure_payload(),
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
        # 存在性与知识库归属检查由路由层负责。在这里去重，
        # 可以让下游检索器行为确定，而不扩大职责范围。
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


class IndexStore(Protocol):
    def index_drafts(
        self,
        *,
        knowledge_base_id: str,
        document_id: str,
        filename: str,
        drafts: Sequence[ChunkDraft],
        digest: str,
        chunk_strategy: ChunkStrategy,
    ) -> int: ...
    def document_chunks(self, knowledge_base_id: str, document_id: str) -> list[IndexedChunk]: ...
    def delete_document(self, knowledge_base_id: str, document_id: str) -> None: ...
    def delete_knowledge_base(self, knowledge_base_id: str) -> None: ...
