from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from core.config import Settings
from rag.chunking import ChunkDraft, ChunkMetadata, ChunkStrategy
from rag.contracts import IndexedChunk, RetrievedChunk
from rag.embeddings import OpenAICompatibleEmbeddingFunction, ProviderEmbedding
from rag.nodes import draft_node
from rag.postprocessors import CandidatePostprocessor, Reranker, RerankerError, TEIReranker
from rag.retrievers import ChromaRetriever
from rag.vector_store import DistanceChromaStore


class RAGStore:
    """仅按知识库与文档过滤的单一 Chroma collection。"""

    def __init__(self, settings: Settings, *, maintenance: bool = False):
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.embedding_function: EmbeddingFunction[Documents] | None = None
        self.reranker: Reranker | None = (
            TEIReranker(base_url=settings.reranker_base_url, api_key=settings.reranker_api_key)
            if settings.reranker_base_url
            else None
        )
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
        names = {collection.name for collection in self.client.list_collections()}
        target = f"{settings.embedding_collection}-li-v1"
        if (
            not maintenance
            and target not in names
            and settings.embedding_collection in names
            and self.client.get_collection(
                settings.embedding_collection, embedding_function=None
            ).count()
        ):
            raise ValueError("Legacy index exists; stop writers and run rag.migrate before startup")
        if not maintenance and target not in names and settings.db_path.is_file():
            with sqlite3.connect(
                settings.db_path.resolve().as_uri() + "?mode=ro", uri=True
            ) as conn:
                if conn.execute(
                    "SELECT 1 FROM documents WHERE status != 'deleted' AND chunk_count > 0 LIMIT 1"
                ).fetchone():
                    raise ValueError(
                        "Existing documents require offline rag.migrate before startup"
                    )
        self.collection: Collection = self.client.get_or_create_collection(
            name=f"{settings.embedding_collection}-li-v1",
            metadata={
                "index_format": "li-v1",
                "migration_complete": not maintenance,
                "embedding_model": settings.embedding_model or "chroma_default",
                "embedding_dimensions": settings.embedding_dimensions or 0,
            },
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )

        if self.collection.configuration.get("hnsw", {}).get("space") != "cosine":
            raise ValueError("Index distance space mismatch; rebuild with cosine configuration")
        if self.collection.metadata.get("index_format") != "li-v1":
            raise ValueError("Index format mismatch; run the offline index conversion first")
        if not maintenance and not self.collection.metadata.get("migration_complete", False):
            raise ValueError("Index conversion incomplete; finish rag.migrate before startup")
        self.embed_model = ProviderEmbedding(self.embedding_function or DefaultEmbeddingFunction())
        self.vector_store = DistanceChromaStore(chroma_collection=self.collection)

    def recreate_collection(self) -> None:
        """全量重建索引时，仅删除并重建此 embedding 空间的 collection。"""
        try:
            self.client.delete_collection(self.collection.name)
        except ValueError:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata=self.collection.metadata,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )

        self.vector_store = DistanceChromaStore(chroma_collection=self.collection)

    def close(self) -> None:
        if isinstance(self.embedding_function, OpenAICompatibleEmbeddingFunction):
            self.embedding_function.client.close()
        if isinstance(self.reranker, TEIReranker):
            self.reranker.close()

    @staticmethod
    def _where(knowledge_base_id: str, document_ids: list[str] | None = None) -> dict:
        terms: list[dict] = [{"knowledge_base_id": knowledge_base_id}]
        if document_ids:
            terms.append(
                {"document_id": document_ids[0]}
                if len(document_ids) == 1
                else {"document_id": {"$in": document_ids}}
            )
        return terms[0] if len(terms) == 1 else {"$and": terms}

    def index_drafts(
        self,
        *,
        knowledge_base_id: str,
        document_id: str,
        filename: str,
        drafts: Sequence[ChunkDraft],
        digest: str,
        chunk_strategy: ChunkStrategy,
    ) -> int:
        if not drafts or any(not draft.content.strip() for draft in drafts):
            raise ValueError("The document did not contain extractable text.")
        nodes = [
            draft_node(
                draft,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                filename=filename,
                digest=digest,
                chunk_index=index,
                chunk_strategy=chunk_strategy,
            )
            for index, draft in enumerate(drafts)
        ]
        vectors = self.embed_model.get_text_embedding_batch([node.text for node in nodes])
        for node, vector in zip(nodes, vectors, strict=True):
            node.embedding = vector
        self.vector_store.add(nodes)
        return len(drafts)

    @staticmethod
    def similarity_score(distance: float | None) -> float:
        """把 Chroma 余弦距离映射为余弦相似度，并收敛到 UI 的 0–1 区间。"""
        if distance is None:
            return 0.0
        return max(0.0, min(1.0, 1.0 - distance))

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
        score_threshold: float | None = None,
        rerank: bool = False,
    ) -> list[RetrievedChunk]:
        if rerank and self.reranker is None:
            raise RerankerError(
                "Reranking is not configured. Set RAG_RERANKER_BASE_URL before enabling rerank."
            )
        # CrossEncoder 需要更大的候选集才能改善最终 top-k 的排序。
        candidate_count = min(100, top_k * 4) if rerank else top_k
        results = ChromaRetriever(
            self.vector_store,
            self.embed_model,
            candidate_count,
            self._where(knowledge_base_id, document_ids),
        ).retrieve(query)
        results = CandidatePostprocessor(
            top_k=top_k,
            threshold=score_threshold,
            reranker=self.reranker if rerank else None,
        ).postprocess_nodes(results, query_str=query)
        chunks = [
            RetrievedChunk(
                chunk_id=item.node.node_id,
                document_id=str(item.node.metadata["document_id"]),
                knowledge_base_id=str(item.node.metadata["knowledge_base_id"]),
                filename=str(item.node.metadata["filename"]),
                content=item.node.text,
                distance=item.score,
                rerank_score=item.node.metadata.get("_rerank_score"),
                chunk_index=int(item.node.metadata["chunk_index"]),
                **ChunkMetadata.from_chroma(item.node.metadata),
            )
            for item in results
        ]
        return chunks

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        payload = self.collection.get(
            where=self._where(knowledge_base_id, [document_id]), include=[]
        )
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def document_chunks(self, knowledge_base_id: str, document_id: str) -> list[IndexedChunk]:
        """读取公开的 Chroma 记录，绝不对源内容重新分块。"""
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
                filename=str(metadata["filename"]),
                **ChunkMetadata.from_chroma(metadata),
            )
            for chunk_id, content, metadata in zip(
                payload.get("ids", []),
                payload.get("documents", []),
                payload.get("metadatas", []),
                strict=True,
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
