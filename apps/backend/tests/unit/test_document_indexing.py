import sqlite3
from pathlib import Path

import pytest

from core.config import Settings
from db import Database
from rag.graph_store import GraphStore
from rag.store import upload_path
from reindex_embeddings import main, read_catalog, rebuild
from services.document_indexing import DocumentIndexingService


class MemoryStore:
    def __init__(self):
        self.records = {}
        self.fail_write = False
        self.fail_delete = False
        self.recreated = False

    def index_drafts(self, **kwargs):
        for index, draft in enumerate(kwargs["drafts"]):
            self.records[f"{kwargs['document_id']}:{index}"] = draft.content
            if self.fail_write:
                raise RuntimeError("embedding failure")
        return len(kwargs["drafts"])

    def delete_document(self, kb_id, doc_id):
        if self.fail_delete:
            raise RuntimeError("Chroma unavailable")
        self.records = {
            key: value for key, value in self.records.items() if not key.startswith(doc_id + ":")
        }

    def recreate_collection(self):
        self.recreated = True
        self.records = {}


@pytest.fixture
def context(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    db = Database(settings.db_path)
    db.initialize()
    db.bootstrap_admin("admin@example.com", "hash")
    user = db.user_by_email("admin@example.com")
    kb = db.create_knowledge_base("KB", "", 100, 20, "structure")
    store = MemoryStore()
    graph = GraphStore(db)
    return settings, db, user, kb, store, graph, DocumentIndexingService(db, store, graph, settings)


def upload(context, content=b"# Title\nBody.", filename="doc.md"):
    _, _, user, kb, _, _, service = context
    return service.upload(kb, filename=filename, content=content, created_by=user["id"])


def test_rebuild_replaces_old_tail_and_invalidates_same_sha_graph(context):
    settings, db, _, kb, store, graph, service = context
    document = upload(context)
    for index in range(1, 5):
        store.records[f"{document['id']}:{index}"] = "stale"
    db.run("UPDATE graph_document_states SET status='ready'")
    db.run("INSERT INTO entities VALUES('old',?, 'Old','old','person','now','now')", (kb["id"],))
    db.run(
        "INSERT INTO entity_mentions VALUES('mention','old',?,?,?,0,3)",
        (kb["id"], document["id"], f"{document['id']}:4"),
    )
    service.index_document(kb, document)
    assert store.records == {f"{document['id']}:0": "Title\n\nBody."}
    assert db.document(kb["id"], document["id"])["status"] == "ready"
    assert graph.document_states(kb["id"])[0]["status"] == "not_built"
    assert db.one("SELECT 1 FROM entity_mentions") is None
    assert db.one("SELECT 1 FROM entities") is None
    assert upload_path(settings.uploads_dir, kb["id"], document["stored_filename"]).exists()


def test_rebuild_parse_failure_preserves_existing_index_and_source(context):
    settings, db, _, kb, store, graph, service = context
    document = upload(context)
    source = upload_path(settings.uploads_dir, kb["id"], document["stored_filename"])
    source.write_bytes(b"# headings only")
    before = dict(store.records)
    with pytest.raises(ValueError, match="SHA256"):
        service.index_document(kb, document)
    assert store.records == before and source.exists()
    assert db.document(kb["id"], document["id"])["status"] == "ready"
    assert graph.document_states(kb["id"])[0]["status"] == "not_built"


@pytest.mark.parametrize("reupload", [False, True])
def test_partial_upload_failure_deletes_only_new_source_and_restores_old(context, reupload):
    settings, db, _, kb, store, graph, _ = context
    old = upload(context) if reupload else None
    old_source = (
        upload_path(settings.uploads_dir, kb["id"], old["stored_filename"]) if old else None
    )
    if old:
        db.set_document_status(kb["id"], old["id"], "failed")
    store.fail_write = True
    with pytest.raises(RuntimeError, match="embedding"):
        upload(context)
    document = db.documents(kb["id"])[0]
    assert document["status"] == "failed" and store.records == {}
    assert graph.document_states(kb["id"]) == []
    sources = list((settings.uploads_dir / kb["id"] / "uploads").glob("*"))
    assert sources == ([old_source] if old else [])
    if old:
        assert document["stored_filename"] == old["stored_filename"]


def test_successful_reupload_removes_old_unreferenced_source(context):
    settings, db, _, kb, _, _, _ = context
    old = upload(context)
    source = upload_path(settings.uploads_dir, kb["id"], old["stored_filename"])
    db.set_document_status(kb["id"], old["id"], "failed")
    new = upload(context)
    assert new["id"] == old["id"] and new["status"] == "ready"
    assert new["stored_filename"] != old["stored_filename"] and not source.exists()


def test_rebuild_write_failure_keeps_owned_existing_source(context):
    settings, db, _, kb, store, graph, service = context
    document = upload(context)
    source = upload_path(settings.uploads_dir, kb["id"], document["stored_filename"])
    store.fail_write = True
    with pytest.raises(RuntimeError, match="embedding"):
        service.index_document(kb, document)
    assert source.exists() and store.records == {}
    assert db.document(kb["id"], document["id"])["status"] == "failed"
    assert graph.document_states(kb["id"]) == []


def test_graph_helper_failure_rolls_back_ready_and_compensates(context, monkeypatch):
    _, db, _, kb, store, graph, service = context
    document = upload(context)

    def broken(conn, **kwargs):
        assert conn.in_transaction
        assert (
            conn.execute("SELECT status FROM documents WHERE id=?", (document["id"],)).fetchone()[0]
            == "ready"
        )
        # 另一个连接不能看到尚未提交的 ready 状态更新。
        assert db.document(kb["id"], document["id"])["status"] == "indexing"
        raise RuntimeError("graph upsert failure")

    monkeypatch.setattr(graph, "mark_not_built_in_tx", broken)
    with pytest.raises(RuntimeError, match="upsert"):
        service.index_document(kb, document)
    assert db.document(kb["id"], document["id"])["status"] == "failed"
    assert store.records == {} and graph.document_states(kb["id"]) == []


def test_helpers_neither_acquire_connections_nor_commit(context, monkeypatch):
    _, db, _, kb, _, graph, _ = context
    document = upload(context)
    db.set_document_status(kb["id"], document["id"], "indexing")
    with db.connection() as conn:

        def forbidden():
            raise AssertionError("helper acquired another connection")

        monkeypatch.setattr(db, "connection", forbidden)
        conn.execute("BEGIN IMMEDIATE")
        db.set_document_ready_in_tx(
            conn,
            knowledge_base_id=kb["id"],
            document_id=document["id"],
            chunk_count=1,
            expected_sha256=document["sha256"],
        )
        graph.mark_not_built_in_tx(
            conn,
            knowledge_base_id=kb["id"],
            document_id=document["id"],
            source_sha256=document["sha256"],
        )
        assert conn.in_transaction
        conn.rollback()
        assert (
            conn.execute("SELECT status FROM documents WHERE id=?", (document["id"],)).fetchone()[0]
            == "indexing"
        )
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="SHA256"):
            db.set_document_ready_in_tx(
                conn,
                knowledge_base_id=kb["id"],
                document_id=document["id"],
                chunk_count=1,
                expected_sha256="wrong",
            )
        conn.rollback()


def test_vector_cleanup_failure_is_recorded_for_retry(context):
    _, db, _, kb, store, graph, service = context
    document = upload(context)
    store.fail_delete = True
    with pytest.raises(RuntimeError, match="Chroma"):
        service.index_document(kb, document)
    failed = db.document(kb["id"], document["id"])
    assert (
        failed["status"] == "failed"
        and "vectors cleanup failed (retry required)" in failed["error_message"]
    )
    assert graph.document_states(kb["id"]) == []


def test_upload_parse_failure_retains_failed_record_without_new_source(context):
    settings, db, _, kb, store, _, _ = context
    with pytest.raises(ValueError, match="body text"):
        upload(context, b"# headings only")
    assert db.documents(kb["id"])[0]["status"] == "failed"
    assert store.records == {} and list(settings.uploads_dir.rglob("*.md")) == []


def test_dry_run_uses_read_only_catalog_and_does_not_initialize_resources(
    context, monkeypatch, capsys
):
    import reindex_embeddings

    settings, db, _, kb, store, _graph, _ = context
    document = upload(context)
    before = db.document(kb["id"], document["id"])

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run accessed a writable resource")

    monkeypatch.setattr(reindex_embeddings, "RAGStore", forbidden)
    monkeypatch.setattr(Database, "connection", forbidden)
    monkeypatch.setattr(Database, "initialize", forbidden)
    monkeypatch.setattr(
        "sys.argv", ["reindex_embeddings", "--data-dir", str(settings.data_dir), "--dry-run"]
    )
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "external-test")
    main()
    assert "strategy=structure chunks=1" in capsys.readouterr().out
    # 不使用被刻意禁止的仓储连接来读取。
    with sqlite3.connect(settings.db_path) as conn:
        conn.row_factory = sqlite3.Row
        assert (
            dict(conn.execute("SELECT * FROM documents WHERE id=?", (document["id"],)).fetchone())
            == before
        )
    assert not store.recreated


def test_preflight_failure_does_not_delete_collection_or_change_states(context):
    settings, db, _, kb, store, _, _ = context
    document = upload(context)
    upload_path(settings.uploads_dir, kb["id"], document["stored_filename"]).unlink()
    before = dict(store.records)
    assert rebuild(settings, db, store) == (0, 1)
    assert not store.recreated and store.records == before
    assert db.document(kb["id"], document["id"])["status"] == "ready"


def test_collection_rebuild_interrupt_invalidates_all_documents_first(context):
    settings, db, _, kb, store, graph, _ = context
    documents = [upload(context), upload(context, b"# Other\nDifferent body.", "other.md")]
    db.run("UPDATE graph_document_states SET status='ready'")

    def interrupted():
        assert all(db.document(kb["id"], doc["id"])["status"] == "indexing" for doc in documents)
        assert all(state["status"] == "stale" for state in graph.document_states(kb["id"]))
        raise KeyboardInterrupt

    store.recreate_collection = interrupted
    with pytest.raises(KeyboardInterrupt):
        rebuild(settings, db, store)
    assert all(db.document(kb["id"], doc["id"])["status"] == "indexing" for doc in documents)


def test_rebuild_dispatches_persisted_strategy(context):
    settings, db, _, kb, store, graph, _ = context
    document = upload(context)
    assert rebuild(settings, db, store) == (1, 0)
    assert store.recreated and store.records == {f"{document['id']}:0": "Title\n\nBody."}
    assert graph.document_states(kb["id"])[0]["status"] == "not_built"


def test_missing_database_dry_run_does_not_create_it(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "absent")
    with pytest.raises(ValueError, match="does not exist"):
        read_catalog(settings)
    assert not settings.data_dir.exists()


def test_read_only_preflight_rejects_noncurrent_schema_without_changing_it(context):
    settings, db, *_ = context
    db.run("ALTER TABLE knowledge_bases DROP COLUMN chunk_strategy")
    with pytest.raises(ValueError, match="does not match the current schema"):
        read_catalog(settings)
    assert "chunk_strategy" not in [
        row["name"] for row in db.many("PRAGMA table_info(knowledge_bases)")
    ]


def test_uploaded_source_unlink_failure_is_recorded(context, monkeypatch):
    _, db, _, kb, store, _, _ = context
    store.fail_write = True

    def broken(*args, **kwargs):
        raise OSError("unlink failed")

    monkeypatch.setattr(Path, "unlink", broken)
    with pytest.raises(RuntimeError, match="embedding"):
        upload(context)
    assert "source cleanup failed" in db.documents(kb["id"])[0]["error_message"]


def test_graph_cleanup_failure_keeps_old_graph_unqueryable(context, monkeypatch):
    _, db, _, kb, _, graph, service = context
    document = upload(context)
    db.run("UPDATE graph_document_states SET status='ready'")

    def broken(**kwargs):
        raise RuntimeError("graph cleanup unavailable")

    monkeypatch.setattr(graph, "cleanup_document", broken)
    with pytest.raises(RuntimeError, match="cleanup unavailable"):
        service.index_document(kb, document)
    assert graph.document_states(kb["id"])[0]["status"] == "stale"
    assert db.document(kb["id"], document["id"])["status"] == "failed"


def test_legal_source_reuse_with_upload_operation_never_unlinks_existing_file(context):
    settings, _, _, kb, store, _, service = context
    document = upload(context)
    source = upload_path(settings.uploads_dir, kb["id"], document["stored_filename"])
    store.fail_write = True
    with pytest.raises(RuntimeError, match="embedding"):
        service.index_document(
            kb, document, operation="upload", created_source_in_this_attempt=False
        )
    assert source.exists()


def test_old_source_cleanup_failure_preserves_committed_success(context, monkeypatch):
    settings, db, _, kb, _, graph, _ = context
    old = upload(context)
    old_source = upload_path(settings.uploads_dir, kb["id"], old["stored_filename"])
    db.set_document_status(kb["id"], old["id"], "failed")
    original_unlink = Path.unlink

    def broken(path, **kwargs):
        if path == old_source:
            raise OSError("old source is locked")
        return original_unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", broken)
    new = upload(context)
    assert new["status"] == "ready" and "old source cleanup failed" in new["error_message"]
    assert str(old_source) in new["error_message"]
    assert old_source.exists()
    assert new["stored_filename"] != old["stored_filename"]
    assert graph.document_states(kb["id"])[0]["status"] == "not_built"
