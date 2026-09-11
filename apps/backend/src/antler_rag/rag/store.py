from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import Settings


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    filename: str
    content: str
    distance: float | None
    chunk_index: int


class RAGStore:
    """One Chroma collection with mandatory tenant and knowledge-base metadata filters."""

    def __init__(self, settings: Settings):
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.collection: Collection = self.client.get_or_create_collection(
            name=settings.collection, metadata={"hnsw:space": "cosine"}
        )

    @staticmethod
    def _where(
        tenant_id: str, knowledge_base_id: str, document_ids: list[str] | None = None
    ) -> dict:
        terms: list[dict] = [{"tenant_id": tenant_id}, {"knowledge_base_id": knowledge_base_id}]
        if document_ids:
            terms.append(
                {"document_id": document_ids[0]}
                if len(document_ids) == 1
                else {"document_id": {"$in": document_ids}}
            )
        return {"$and": terms}

    def index(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
        filename: str,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        digest: str,
    ) -> int:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", ". ", " ", ""],
        )
        chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
        if not chunks:
            raise ValueError("The document did not contain extractable text.")
        ids = [f"{document_id}:{index}" for index in range(len(chunks))]
        metadata = [
            {
                "tenant_id": tenant_id,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
                "filename": filename,
                "sha256": digest,
                "chunk_index": index,
            }
            for index in range(len(chunks))
        ]
        self.collection.add(ids=ids, documents=chunks, metadatas=metadata)
        return len(chunks)

    def retrieve(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        result = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=self._where(tenant_id, knowledge_base_id, document_ids),
            include=["documents", "metadatas", "distances"],
        )
        return [
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=str(metadata["document_id"]),
                knowledge_base_id=str(metadata["knowledge_base_id"]),
                filename=str(metadata["filename"]),
                content=document,
                distance=distance,
                chunk_index=int(metadata["chunk_index"]),
            )
            for chunk_id, document, metadata, distance in zip(
                result.get("ids", [[]])[0],
                result.get("documents", [[]])[0],
                result.get("metadatas", [[]])[0],
                result.get("distances", [[]])[0],
                strict=True,
            )
        ]

    def delete_document(self, tenant_id: str, knowledge_base_id: str, document_id: str) -> None:
        payload = self.collection.get(
            where=self._where(tenant_id, knowledge_base_id, [document_id]), include=[]
        )
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def delete_knowledge_base(self, tenant_id: str, knowledge_base_id: str) -> None:
        payload = self.collection.get(where=self._where(tenant_id, knowledge_base_id), include=[])
        if payload.get("ids"):
            self.collection.delete(ids=payload["ids"])

    def healthy(self) -> bool:
        self.collection.count()
        return True


def upload_path(root: Path, tenant_id: str, knowledge_base_id: str, stored_filename: str) -> Path:
    """Only server-generated UUID filenames reach this trusted tenant namespace."""
    return root / tenant_id / "knowledge-bases" / knowledge_base_id / "uploads" / stored_filename
