"""维护窗口内手动重建文档向量索引，执行前先进行严格只读的预检。

通过 python -m reindex_embeddings 执行；--dry-run 仅检查，--confirm 正式重建。
正式重建前需停止所有写入者并备份完整数据目录，本脚本不负责旧数据库迁移。
"""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from core.config import Settings
from db import Database
from db.repository import now
from db.schema import validate_schema
from rag import RAGStore
from rag.graph_store import GraphStore
from rag.store import upload_path
from services.document_indexing import DocumentIndexingService, prepare_source


def read_catalog(settings: Settings) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """只读获取待重建的知识库及文档，不创建目录、迁移结构、配置 WAL 或打开 Chroma。"""
    if not settings.db_path.is_file():
        raise ValueError(
            "Database does not exist; initialize the service with a new data directory first"
        )
    # 强制使用 SQLite 只读模式，避免预检意外创建或修改数据库。
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        validate_schema(conn)
        targets = []
        # 排除已删除知识库；包含待索引、索引中和失败文档，便于恢复未完成的索引。
        for kb in conn.execute(
            "SELECT * FROM knowledge_bases WHERE status != 'deleted' ORDER BY id"
        ).fetchall():
            for document in conn.execute(
                "SELECT * FROM documents WHERE knowledge_base_id=? AND status IN ('ready','indexing','failed','pending') ORDER BY id",
                (kb["id"],),
            ).fetchall():
                targets.append((dict(kb), dict(document)))
        return targets


def preflight(
    settings: Settings, targets: list[tuple[dict, dict]]
) -> tuple[list[tuple[dict, dict, list]], list[str]]:
    """解析原上传文件并按知识库配置分块，返回准备好的分块及全部预检错误。"""
    prepared = []
    errors = []
    for kb, document in targets:
        source = upload_path(settings.uploads_dir, kb["id"], document["stored_filename"])
        try:
            # 这里只准备分块，不调用 embedding 服务，也不写入向量索引。
            drafts = prepare_source(kb, document, source)
            prepared.append((kb, document, drafts))
        except Exception as error:  # noqa: BLE001 -- 收集每份文档的维护错误，供调用方终止重建
            errors.append(f"{kb['id']}/{document['id']} ({document['filename']}): {error}")
    return prepared, errors


def rebuild(settings: Settings, database: Database, store: RAGStore) -> tuple[int, int]:
    """全量预检通过后，先更新文档和图谱状态，再替换向量；返回成功数与失败数。"""
    targets = read_catalog(settings)
    prepared, errors = preflight(settings, targets)
    # 任一源文件预检失败都中止重建，此时尚未修改文档状态或删除 collection。
    if errors:
        for error in errors:
            print(f"Preflight failed: {error}")
        return 0, len(errors)
    graph = GraphStore(database)
    service = DocumentIndexingService(database, store, graph, settings)
    # 必须先提交状态变更，再删除 collection。即使后续中断，未处理文档也会保持
    # indexing 状态，旧图谱事实不可查询，避免将失效索引误认为可用。
    with database.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for kb, document, _ in prepared:
                conn.execute(
                    "UPDATE documents SET status='indexing',updated_at=? WHERE knowledge_base_id=? AND id=?",
                    (now(), kb["id"], document["id"]),
                )
            conn.execute("UPDATE graph_document_states SET status='stale',updated_at=?", (now(),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    # 删除并重建当前 embedding 配置对应的整个 collection，覆盖所有目标知识库。
    store.recreate_collection()
    indexed = failed = 0
    for kb, document, drafts in prepared:
        try:
            # 复用上传文档的索引流程，使用已准备的分块生成向量并更新文档状态。
            # 旧图谱来源也会被清理；图谱需通过单独的图谱重建入口重新生成。
            service.index_document(kb, document, drafts=drafts)
            indexed += 1
        except Exception as error:  # noqa: BLE001 -- 记录单份文档失败并继续处理其余文档
            print(f"Rebuild failed: {document['id']}: {error}")
            failed += 1
    return indexed, failed


def main() -> None:
    """命令行入口：选择只读预检或正式重建，并通过退出码报告失败。"""
    parser = argparse.ArgumentParser(
        description="Rebuild vectors during a maintenance window with all writers stopped"
    )
    parser.add_argument("--data-dir", help="Override RAG_DATA_DIR")
    # 必须显式选择一种模式，防止未指定参数时直接执行全量重建。
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Delete and rebuild the entire active collection after a backup",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only schema/source/configuration check; no embedding or Chroma",
    )
    args = parser.parse_args()
    settings = Settings(data_dir=args.data_dir) if args.data_dir else Settings()
    if not settings.embedding_model:
        parser.error("Set RAG_EMBEDDING_MODEL before rebuilding an external embedding index.")
    try:
        targets = read_catalog(settings)
        prepared, errors = preflight(settings, targets)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    # 只读模式在创建 RAGStore 前返回，不打开 Chroma，也不调用 embedding 服务。
    if args.dry_run:
        for kb, document, drafts in prepared:
            print(
                f"{kb['name']}/{document['filename']}: strategy={kb['chunk_strategy']} chunks={len(drafts)}"
            )
        for error in errors:
            print(f"Preflight failed: {error}")
        print(
            f"Prepared {len(prepared)} documents; {sum(len(drafts) for _, _, drafts in prepared)} chunks; {len(errors)} failures."
        )
        if errors:
            parser.exit(1)
        return
    if errors:
        parser.exit(1, "\n".join(errors) + "\nPreflight failed; collection was preserved.\n")
    store = RAGStore(settings)
    try:
        # 正式替换前再次预检，不能将之前的 dry-run 或预检结果视为当前有效结果。
        indexed, failed = rebuild(settings, Database(settings.db_path), store)
        print(f"Rebuilt {indexed} documents; {failed} documents failed.")
        if failed:
            parser.exit(1)
    finally:
        # 无论重建成功、失败还是以非零退出码结束，都释放向量存储相关资源。
        store.close()


if __name__ == "__main__":
    # 仅直接运行脚本或通过 python -m 执行时启动；被其他模块导入时不执行。
    main()
