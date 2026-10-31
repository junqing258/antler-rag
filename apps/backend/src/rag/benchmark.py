"""只读的固定向量对比工具，使用提供的 JSONL 业务问题集。

每行格式：{"knowledge_base_id": "...", "query": "...", "relevant_ids": ["doc:0"]}。
不做 embedding/LLM 调用：使用旧集合中已存储的向量作为查询向量，
仅做格式与性能对比。语义指标需要真实查询向量，
可在每行中以 `embedding` 字段提供。
"""

import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter

import chromadb

from core.config import Settings
from rag.chunking import ChunkMetadata
from rag.contracts import RetrievedChunk
from rag.embeddings import ProviderEmbedding
from rag.store import RAGStore
from rag.vector_store import DistanceChromaStore


def compare(settings, questions, *, source_collection=None, runs=100):
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    old = client.get_collection(
        source_collection or settings.embedding_collection, embedding_function=None
    )
    new = client.get_collection(f"{settings.embedding_collection}-li-v1", embedding_function=None)
    adapter = DistanceChromaStore(chroma_collection=new)
    store = object.__new__(RAGStore)
    store.collection, store.vector_store, store.reranker = new, adapter, None
    rows = []
    for question in questions:
        where = {"knowledge_base_id": question["knowledge_base_id"]}
        vector = question.get("embedding")
        if vector is None:
            payload = old.get(where=where, limit=1, include=["embeddings"])
            vector = payload["embeddings"][0].tolist()

        def baseline(vector=vector, where=where):
            result = old.query(
                query_embeddings=[vector],
                n_results=5,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            # 复现旧的结果映射，包括结构校验。
            chunks = [
                RetrievedChunk(
                    chunk_id=node_id,
                    document_id=str(metadata["document_id"]),
                    knowledge_base_id=str(metadata["knowledge_base_id"]),
                    filename=str(metadata["filename"]),
                    content=text,
                    distance=distance,
                    chunk_index=int(metadata["chunk_index"]),
                    **ChunkMetadata.from_chroma(metadata),
                )
                for node_id, text, metadata, distance in zip(
                    result["ids"][0],
                    result["documents"][0],
                    result["metadatas"][0],
                    result["distances"][0],
                    strict=True,
                )
            ]
            return [chunk.chunk_id for chunk in chunks]

        store.embed_model = ProviderEmbedding(lambda texts, vector=vector: [vector for _ in texts])

        def candidate(question=question):
            return [
                chunk.chunk_id
                for chunk in store.retrieve(
                    knowledge_base_id=question["knowledge_base_id"],
                    query=question["query"],
                    top_k=5,
                )
            ]

        # 计时前先预热两条路径；计时调用至少 100 次。
        for _ in range(10):
            baseline()
            candidate()
        timings = [[], []]
        ids = [None, None]
        for _ in range(max(100, runs)):
            for i, function in enumerate((baseline, candidate)):
                started = perf_counter()
                ids[i] = function()
                timings[i].append((perf_counter() - started) * 1000)
        relevant = set(question.get("relevant_ids", []))
        metrics = []
        for values, results in zip(timings, ids, strict=True):
            metrics.append(
                {
                    "p50_ms": median(values),
                    "p95_ms": sorted(values)[int(len(values) * 0.95)],
                    "recall_at_5": len(relevant.intersection(results)) / len(relevant)
                    if relevant
                    else None,
                    "mrr": next(
                        (1 / rank for rank, item in enumerate(results, 1) if item in relevant), 0
                    )
                    if relevant
                    else None,
                }
            )
        rows.append(
            {
                "query": question["query"],
                "semantic": "embedding" in question,
                "ids_equal": ids[0] == ids[1],
                "baseline": metrics[0],
                "candidate": metrics[1],
                "p95_ratio": metrics[1]["p95_ms"] / metrics[0]["p95_ms"],
            }
        )
    return {"questions": rows, "embedding_calls": 0, "llm_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("questions", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-collection")
    args = parser.parse_args()
    questions = [
        json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()
    ]
    result = compare(Settings(), questions, source_collection=args.source_collection)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
