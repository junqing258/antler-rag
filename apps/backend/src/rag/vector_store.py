"""Chroma 适配器，在查询结果中保留原始余弦距离。"""

from llama_index.core.vector_stores.types import VectorStoreQueryResult
from llama_index.core.vector_stores.utils import metadata_dict_to_node
from llama_index.vector_stores.chroma import ChromaVectorStore


class DistanceChromaStore(ChromaVectorStore):
    def _query(self, query_embeddings, n_results, where, **kwargs):
        result = self._collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where or None,
            include=["documents", "metadatas", "distances"],
            **kwargs,
        )
        nodes = [
            metadata_dict_to_node(metadata, text=text)
            for metadata, text in zip(result["metadatas"][0], result["documents"][0], strict=True)
        ]
        return VectorStoreQueryResult(
            nodes=nodes,
            ids=result["ids"][0],
            similarities=result["distances"][0],
        )
