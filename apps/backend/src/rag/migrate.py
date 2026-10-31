"""离线、报告优先的迁移转换。绝不能与应用写入方同时运行。

python -m rag.migrate --report migration.json [--apply] [--rebuild]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import chromadb
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from core.config import Settings
from db import Database
from rag.chunking import ChunkMetadata
from rag.embeddings import validate_vectors
from rag.graph_store import GraphStore
from rag.store import RAGStore, upload_path
from reindex_embeddings import read_catalog
from services.document_indexing import DocumentIndexingService, prepare_source


def convert(settings, *, apply=False, rebuild=False, report_path: Path, source_collection=None):
    report = {"complete": False, "business_state_changed": False, "documents": [], "errors": []}
    store = None

    def persist():
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_suffix(report_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        temporary.replace(report_path)

    try:
        database = Database(settings.db_path)
        catalog = read_catalog(settings)
        if not settings.chroma_dir.is_dir():
            raise ValueError("Chroma directory does not exist")
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        old = client.get_collection(
            source_collection or settings.embedding_collection, embedding_function=None
        )
        if old.name == f"{settings.embedding_collection}-li-v1":
            raise ValueError("Source and target must be different collections")
        report["source_collection"] = old.name
        report["target_collection"] = f"{settings.embedding_collection}-li-v1"
        records = old.get(include=["documents", "metadatas", "embeddings"])
        by_document = {}
        for index, metadata in enumerate(records["metadatas"]):
            by_document.setdefault(metadata["document_id"], []).append(index)
        work = []
        seen = set()
        for kb, doc in catalog:
            seen.add(doc["id"])
            drafts = prepare_source(
                kb, doc, upload_path(settings.uploads_dir, kb["id"], doc["stored_filename"])
            )
            indices = by_document.get(doc["id"], [])
            reasons = []
            if doc["status"] != "ready":
                reasons.append("document_not_ready")
            if len(indices) != len(drafts) or doc["chunk_count"] != len(drafts):
                reasons.append("chunk_count")
            expected = {f"{doc['id']}:{i}": draft for i, draft in enumerate(drafts)}
            for i in indices:
                metadata, text = records["metadatas"][i], records["documents"][i]
                draft = expected.get(records["ids"][i])
                stored_structure = ChunkMetadata.from_chroma(metadata)
                if (
                    draft is None
                    or draft.content != text
                    or any(metadata.get(k) != v for k, v in draft.chroma_metadata().items())
                    or any(
                        stored_structure.get(k) != v
                        for k, v in draft.structure_payload().items()
                        if k not in ("chunk_strategy", "chunker_version")
                    )
                    or metadata.get("knowledge_base_id") != kb["id"]
                    or metadata.get("sha256") != doc["sha256"]
                    or metadata.get("filename") != doc["filename"]
                    or metadata.get("chunk_strategy") != kb["chunk_strategy"]
                    or metadata.get("chunk_index") != int(records["ids"][i].rsplit(":", 1)[1])
                ):
                    reasons.append("content_or_metadata")
                try:
                    validate_vectors(
                        [records["embeddings"][i]],
                        1,
                        settings.embedding_dimensions or len(records["embeddings"][0]),
                    )
                except (TypeError, ValueError):
                    reasons.append("embedding")
            if (old.metadata or {}).get("embedding_model", "chroma_default") != (
                settings.embedding_model or "chroma_default"
            ):
                reasons.append("model")
            if old.name != settings.embedding_collection:
                reasons.append("model_identity")
            if (old.metadata or {}).get("embedding_dimensions", 0) != (
                settings.embedding_dimensions or 0
            ):
                reasons.append("dimensions_config")
            if old.configuration.get("hnsw", {}).get("space") != "cosine":
                reasons.append("distance_space")
            reasons = sorted(set(reasons))
            item = {
                "document_id": doc["id"],
                "branch": "rebuild" if reasons else "format",
                "reasons": reasons,
                "chunks": len(drafts),
                "verified": False,
            }
            report["documents"].append(item)
            work.append((kb, doc, drafts, indices, item))
            if reasons and not rebuild:
                report["errors"].append(f"{doc['id']}: rebuild required: {reasons}")
        if set(by_document) - seen:
            raise ValueError("Orphan legacy records; repair before conversion")
        if report["errors"]:
            return report
        if not apply:
            report["complete"] = True
            return report
        persist()
        store = RAGStore(settings, maintenance=True)
        store.collection.modify(metadata={**store.collection.metadata, "migration_complete": False})
        service = DocumentIndexingService(database, store, GraphStore(database), settings)
        for kb, doc, drafts, indices, item in work:
            if item["branch"] == "rebuild":
                report["business_state_changed"] = True
                persist()
                service.index_document(kb, doc, drafts=drafts)
            else:
                store.delete_document(kb["id"], doc["id"])
                nodes = []
                for i in indices:
                    metadata = records["metadatas"][i]
                    nodes.append(
                        TextNode(
                            id_=records["ids"][i],
                            text=records["documents"][i],
                            metadata=metadata,
                            embedding=list(map(float, records["embeddings"][i])),
                            excluded_embed_metadata_keys=list(metadata),
                            excluded_llm_metadata_keys=list(metadata),
                            relationships={
                                NodeRelationship.SOURCE: RelatedNodeInfo(node_id=doc["id"])
                            },
                        )
                    )
                if nodes:
                    store.vector_store.add(nodes)
            actual = store.document_chunks(kb["id"], doc["id"])
            if [(c.chunk_id, c.content) for c in actual] != [
                (f"{doc['id']}:{i}", draft.content) for i, draft in enumerate(drafts)
            ]:
                raise ValueError("Target verification failed")
            target_records = store.collection.get(
                where=store._where(kb["id"], [doc["id"]]), include=["embeddings", "metadatas"]
            )
            validate_vectors(
                target_records["embeddings"], len(drafts), settings.embedding_dimensions
            )
            for chunk, draft in zip(actual, drafts, strict=True):
                if any(
                    chunk.chroma_metadata().get(k) != v for k, v in draft.chroma_metadata().items()
                ):
                    raise ValueError("Target structure verification failed")
            if item["branch"] == "rebuild":
                current = database.document(kb["id"], doc["id"])
                graph_state = database.one(
                    "SELECT status FROM graph_document_states WHERE knowledge_base_id=? AND document_id=?",
                    (kb["id"], doc["id"]),
                )
                mentions = database.one(
                    "SELECT COUNT(*) AS count FROM entity_mentions WHERE knowledge_base_id=? AND document_id=?",
                    (kb["id"], doc["id"]),
                )
                if (
                    current["status"] != "ready"
                    or current["chunk_count"] != len(drafts)
                    or not graph_state
                    or graph_state["status"] != "not_built"
                    or mentions["count"]
                ):
                    raise ValueError("Rebuild business/graph verification failed")
            if item["branch"] == "format":
                target = store.collection.get(
                    ids=[records["ids"][i] for i in indices], include=["embeddings", "metadatas"]
                )
                original = {records["ids"][i]: i for i in indices}
                for j, node_id in enumerate(target["ids"]):
                    i = original[node_id]
                    if list(target["embeddings"][j]) != list(records["embeddings"][i]):
                        raise ValueError("Converted vector changed")
                    if any(
                        target["metadatas"][j].get(k) != v
                        for k, v in records["metadatas"][i].items()
                    ):
                        raise ValueError("Converted metadata changed")
            item["verified"] = True
            persist()
            item["body_sha256"] = hashlib.sha256(
                "".join(c.content for c in actual).encode()
            ).hexdigest()
        if store.collection.count() != sum(item["chunks"] for item in report["documents"]):
            raise ValueError("Target global record count mismatch")
        store.collection.modify(metadata={**store.collection.metadata, "migration_complete": True})
        report["complete"] = True
    except Exception as error:  # noqa: BLE001 -- 每次维护运行失败都要留下报告
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        if store:
            store.close()
        persist()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--source-collection", help="模型显式变更时使用的旧集合"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    result = convert(
        Settings(),
        apply=args.apply,
        rebuild=args.rebuild,
        report_path=args.report,
        source_collection=args.source_collection,
    )
    raise SystemExit(0 if result["complete"] else 1)


if __name__ == "__main__":
    main()
