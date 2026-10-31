import asyncio
import hashlib
import json
import threading

import chromadb
import pytest
from llama_index.core.schema import MetadataMode, NodeRelationship
from llama_index.core.vector_stores.utils import metadata_dict_to_node

from core.config import Settings
from db import Database
from rag.chunking import ChunkDraft
from rag.embeddings import ProviderEmbedding, validate_vectors
from rag.execution import run_sync
from rag.migrate import convert
from rag.nodes import draft_node
from rag.store import RAGStore, upload_path
from services.document_indexing import prepare_drafts


def test_nodes_exclude_metadata_and_preserve_source():
    draft = ChunkDraft(content=" exact\n", heading_path=["甲", "乙"], section_id="s000001")
    node = draft_node(
        draft,
        knowledge_base_id="kb",
        document_id="doc",
        filename="secret.md",
        digest="sha",
        chunk_index=0,
        chunk_strategy="structure",
    )
    assert node.get_content(MetadataMode.EMBED) == draft.content
    assert node.get_content(MetadataMode.LLM) == draft.content
    assert node.relationships[NodeRelationship.SOURCE].node_id == "doc"


@pytest.mark.parametrize(
    "vectors,dimensions",
    [([[1, 2]], 3), ([[float("nan")]], 1), ([[float("inf")]], 1), ([[]], None)],
)
def test_invalid_vectors(vectors, dimensions):
    with pytest.raises(ValueError):
        validate_vectors(vectors, 1, dimensions)


def local_store(settings):
    store = RAGStore(settings)
    store.embed_model = ProviderEmbedding(
        lambda texts: [[1.0, 0.0] if "positive" in text else [-1.0, 0.0] for text in texts]
    )
    return store


def test_real_chroma_distances_filters_reopen(tmp_path):
    settings = Settings(
        _env_file=None, data_dir=tmp_path, embedding_model=None, reranker_base_url=None
    )
    store = local_store(settings)
    for kb, doc, text in [
        ("kb", "a", "positive"),
        ("kb", "b", "negative"),
        ("other", "c", "positive"),
    ]:
        store.index_drafts(
            knowledge_base_id=kb,
            document_id=doc,
            filename="x.md",
            drafts=[ChunkDraft(content=text)],
            digest="sha",
            chunk_strategy="recursive",
        )
    chunks = store.retrieve(knowledge_base_id="kb", query="positive", top_k=5)
    assert [c.document_id for c in chunks] == ["a", "b"]
    assert chunks[1].distance == pytest.approx(2)
    assert store.similarity_score(chunks[1].distance) == 0
    assert [
        c.document_id
        for c in store.retrieve(
            knowledge_base_id="kb", query="positive", top_k=5, score_threshold=0.5
        )
    ] == ["a"]
    assert [
        c.document_id
        for c in store.retrieve(
            knowledge_base_id="kb", query="positive", top_k=5, document_ids=["b"]
        )
    ] == ["b"]
    store.close()
    reopened = local_store(settings)
    payload = reopened.collection.get(ids=["a:0"], include=["documents", "metadatas"])
    node = metadata_dict_to_node(payload["metadatas"][0], text=payload["documents"][0])
    assert node.node_id == "a:0" and node.text == "positive"
    reopened.delete_document("kb", "a")
    assert reopened.document_chunks("kb", "a") == []
    reopened.close()


def migration_context(tmp_path):
    settings = Settings(
        _env_file=None, data_dir=tmp_path, embedding_model=None, reranker_base_url=None
    )
    db = Database(settings.db_path)
    db.initialize()
    db.bootstrap_admin("admin@example.com", "hash")
    user = db.user_by_email("admin@example.com")
    kb = db.create_knowledge_base("KB", "", 100, 20, "recursive")
    content = b"positive content"
    digest = hashlib.sha256(content).hexdigest()
    doc = db.create_document(kb["id"], "x.md", "x.md", digest, len(content), user["id"])
    source = upload_path(settings.uploads_dir, kb["id"], "x.md")
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    drafts = prepare_drafts(kb, "x.md", content)
    db.set_document_status(kb["id"], doc["id"], "ready", len(drafts))
    old = chromadb.PersistentClient(path=str(settings.chroma_dir)).create_collection(
        settings.embedding_collection, metadata={"hnsw:space": "cosine"}, embedding_function=None
    )
    node = draft_node(
        drafts[0],
        knowledge_base_id=kb["id"],
        document_id=doc["id"],
        filename="x.md",
        digest=digest,
        chunk_index=0,
        chunk_strategy="recursive",
    )
    old.add(
        ids=[node.node_id],
        documents=[node.text],
        metadatas=[node.metadata],
        embeddings=[[1.0, 0.0]],
    )
    return settings, db, kb, doc, old


def test_conversion_zero_embedding_idempotent_and_business_unchanged(tmp_path, monkeypatch):
    settings, db, kb, doc, old = migration_context(tmp_path)
    before = db.document(kb["id"], doc["id"])

    def forbidden(*args, **kwargs):
        raise AssertionError("conversion must not embed")

    monkeypatch.setattr(ProviderEmbedding, "_get_text_embeddings", forbidden)
    with pytest.raises(ValueError, match="Legacy index"):
        RAGStore(settings)
    report = tmp_path / "report.json"
    assert convert(settings, report_path=report)["complete"]
    for _ in range(2):
        result = convert(settings, apply=True, report_path=report)
        assert result["complete"], result
        assert not result["business_state_changed"]
    assert old.count() == 1
    assert db.document(kb["id"], doc["id"]) == before
    assert json.loads(report.read_text())["documents"][0]["verified"]


def test_conversion_rebuild_uses_lifecycle_and_preserves_old(tmp_path, monkeypatch):
    settings, db, kb, doc, old = migration_context(tmp_path)
    old.update(ids=[f"{doc['id']}:0"], documents=["outdated"], embeddings=[[1.0, 0.0]])
    monkeypatch.setattr(
        ProviderEmbedding, "_get_text_embeddings", lambda self, texts: [[1.0, 0.0] for _ in texts]
    )
    result = convert(settings, apply=True, rebuild=True, report_path=tmp_path / "report.json")
    assert result["complete"], result
    assert result["business_state_changed"]
    assert result["documents"][0]["branch"] == "rebuild"
    assert old.get(include=["documents"])["documents"] == ["outdated"]
    assert db.document(kb["id"], doc["id"])["status"] == "ready"


def test_cancelled_worker_keeps_slot_until_actual_completion(monkeypatch):
    from rag import execution

    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(execution, "_slots", slots)
    entered, release = threading.Event(), threading.Event()

    def blocking():
        entered.set()
        release.wait(3)

    async def scenario():
        task = asyncio.create_task(run_sync(blocking))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not slots.acquire(blocking=False)
        release.set()
        for _ in range(100):
            if slots.acquire(blocking=False):
                slots.release()
                return
            await asyncio.sleep(0.001)
        raise AssertionError("slot not released")

    asyncio.run(scenario())


def test_rebuild_failure_blocks_start_and_preserves_legacy(tmp_path, monkeypatch):
    settings, db, kb, doc, old = migration_context(tmp_path)
    old.update(ids=[f"{doc['id']}:0"], documents=["outdated"], embeddings=[[1.0, 0.0]])

    def fail(self, texts):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ProviderEmbedding, "_get_text_embeddings", fail)
    result = convert(settings, apply=True, rebuild=True, report_path=tmp_path / "report.json")
    assert not result["complete"] and result["business_state_changed"]
    assert old.count() == 1
    assert db.document(kb["id"], doc["id"])["status"] == "failed"
    with pytest.raises(ValueError, match="incomplete"):
        RAGStore(settings)
    target = chromadb.PersistentClient(path=str(settings.chroma_dir)).get_collection(
        f"{settings.embedding_collection}-li-v1", embedding_function=None
    )
    assert target.count() == 0


def test_hash_mismatch_aborts_before_target_creation(tmp_path):
    settings, db, kb, doc, old = migration_context(tmp_path)
    before = db.document(kb["id"], doc["id"])
    upload_path(settings.uploads_dir, kb["id"], "x.md").write_bytes(b"changed")
    result = convert(settings, apply=True, rebuild=True, report_path=tmp_path / "report.json")
    assert not result["complete"] and not result["business_state_changed"]
    assert "SHA256" in result["errors"][0]
    assert db.document(kb["id"], doc["id"]) == before
    assert old.count() == 1


def test_synthesis_only_includes_complete_blocks():
    from types import SimpleNamespace

    from rag.synthesis import answer_messages, context_evidence

    items = [
        SimpleNamespace(filename="a", content="A" * 20),
        SimpleNamespace(filename="b", content="B" * 100),
    ]
    selected = context_evidence(items, question="Q", prompt="P", budget=100)
    assert selected == items[:1]
    assert "Source 2" not in answer_messages("P", "Q", selected)[1]["content"]


def test_full_backup_restore_after_interrupted_rebuild(tmp_path):
    """每个阶段都在拷贝 Chroma 前退出；绝不在线程句柄存活时执行恢复。"""
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    live, backup = tmp_path / "live", tmp_path / "backup"
    setup = """
import sys
from pathlib import Path
sys.path.insert(0, 'tests/unit')
from test_llamaindex import migration_context
settings, db, kb, doc, old = migration_context(Path(sys.argv[1]))
db.run("INSERT INTO entities VALUES('entity',?, 'Original','original','person','now','now')", (kb['id'],))
db.run("INSERT INTO entity_mentions VALUES('mention','entity',?,?,?,0,3)", (kb['id'], doc['id'], f"{doc['id']}:0"))
old.update(ids=[f"{doc['id']}:0"], documents=['outdated'], embeddings=[[1., 0.]])
"""
    interrupt = """
import os, sys
from pathlib import Path
from core.config import Settings
from rag.embeddings import ProviderEmbedding
from rag.migrate import convert
# 模拟在 embedding 调用处、索引/图谱清理之后进程被终止。
ProviderEmbedding._get_text_embeddings = lambda *args: os._exit(17)
convert(Settings(_env_file=None, data_dir=Path(sys.argv[1]), embedding_model=None),
        apply=True, rebuild=True, report_path=Path(sys.argv[1])/'report.json')
"""
    verify = """
import hashlib, sys
from pathlib import Path
import chromadb
from core.config import Settings
from db import Database
from rag.store import upload_path
settings = Settings(_env_file=None, data_dir=Path(sys.argv[1]), embedding_model=None)
db = Database(settings.db_path)
doc = db.many("SELECT * FROM documents")[0]
assert doc['status'] == 'ready' and doc['chunk_count'] == 1
assert hashlib.sha256(upload_path(settings.uploads_dir, doc['knowledge_base_id'], doc['stored_filename']).read_bytes()).hexdigest() == doc['sha256']
assert db.many("SELECT * FROM entity_mentions")[0]['id'] == 'mention'
client = chromadb.PersistentClient(path=str(settings.chroma_dir))
assert [c.name for c in client.list_collections()] == [settings.embedding_collection]
assert client.get_collection(settings.embedding_collection, embedding_function=None).get(include=['documents'])['documents'] == ['outdated']
"""
    env = {**os.environ, "PYTHONPATH": str(backend / "src")}
    subprocess.run([sys.executable, "-c", setup, str(live)], cwd=backend, env=env, check=True)
    shutil.copytree(live, backup)
    result = subprocess.run(
        [sys.executable, "-c", interrupt, str(live)], cwd=backend, env=env, check=False
    )
    assert result.returncode == 17
    assert json.loads((live / "report.json").read_text())["business_state_changed"]
    shutil.rmtree(live)
    shutil.copytree(backup, live)
    subprocess.run([sys.executable, "-c", verify, str(live)], cwd=backend, env=env, check=True)


def test_partial_framework_write_is_compensated_by_business_lifecycle(tmp_path, monkeypatch):
    from rag.graph_store import GraphStore
    from services.document_indexing import DocumentIndexingService

    settings, db, kb, doc, old = migration_context(tmp_path)
    assert convert(settings, apply=True, report_path=tmp_path / "report.json")["complete"]
    store = local_store(settings)
    original = store.vector_store.add

    def partial_write(self, nodes, **kwargs):
        original(nodes[:1])
        raise RuntimeError("partial Chroma write")

    monkeypatch.setattr(type(store.vector_store), "add", partial_write)
    service = DocumentIndexingService(db, store, GraphStore(db), settings)
    with pytest.raises(RuntimeError, match="partial Chroma"):
        service.index_document(kb, doc)
    assert store.document_chunks(kb["id"], doc["id"]) == []
    assert db.document(kb["id"], doc["id"])["status"] == "failed"
    assert old.count() == 1
    store.close()
