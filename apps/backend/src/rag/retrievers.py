"""请求级的 LlamaIndex 检索，召回前先应用授权过滤条件。"""

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores.types import VectorStoreQuery


class ChromaRetriever(BaseRetriever):
    def __init__(self, store, embed_model, top_k, where):
        super().__init__()
        self.store, self.embed_model, self.top_k, self.where = store, embed_model, top_k, where

    def _retrieve(self, query_bundle):
        embedding = self.embed_model.get_query_embedding(query_bundle.query_str)
        result = self.store.query(
            VectorStoreQuery(query_embedding=embedding, similarity_top_k=self.top_k),
            where=self.where,
        )
        return [
            NodeWithScore(node=node, score=distance)
            for node, distance in zip(result.nodes, result.similarities, strict=True)
        ]
