"""检索编排，使用稳定且与来源无关的证据模型。

目前向量存储仍是唯一启用的检索器。把它的适配器放在这个
小型服务之后，便于将来加入关键词与图谱检索，而无需改动 HTTP 契约。
"""

from __future__ import annotations

from time import perf_counter
from typing import Protocol

from .contracts import Evidence, RetrievalFilters, RetrievalTrace
from .store import RAGStore


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
    """协调已启用的检索器，当前语义仅为向量检索。"""

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
        # 将来的混合合并器沿用同一规则：每个溯源 chunk 只保留一条。
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
