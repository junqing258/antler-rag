from pathlib import Path

from db import Database
from rag.graph_store import GraphStore


def ready_document(tmp_path: Path) -> tuple[Database, dict[str, str], dict[str, str], GraphStore]:
    database = Database(tmp_path / "app.sqlite3")
    database.migrate()
    database.bootstrap_admin("admin@example.com", "hash")
    user = database.user_by_email("admin@example.com")
    assert user
    knowledge_base = database.create_knowledge_base("KB", "", 900, 150)
    document = database.create_document(
        knowledge_base["id"], "doc.md", "doc.md", "a" * 64, 1, user["id"]
    )
    database.set_document_status(knowledge_base["id"], document["id"], "ready", 1)
    return database, knowledge_base, document, GraphStore(database)


def test_graph_store_marks_ready_document_as_not_built(tmp_path: Path) -> None:
    _, knowledge_base, document, store = ready_document(tmp_path)

    store.mark_not_built(
        knowledge_base_id=knowledge_base["id"], document_id=document["id"], source_sha256="a" * 64
    )

    states = store.document_states(knowledge_base["id"])
    assert len(states) == 1
    assert states[0]["document_id"] == document["id"]
    assert states[0]["status"] == "not_built"


def test_graph_store_cleanup_removes_only_orphaned_provenance(tmp_path: Path) -> None:
    database, knowledge_base, document, store = ready_document(tmp_path)
    user = database.user_by_email("admin@example.com")
    assert user
    kb_id, document_id = knowledge_base["id"], document["id"]
    database.run(
        "INSERT INTO graph_builds VALUES('build',?,?, 'ready','model','v1',1,'now','now','now',NULL)",
        (kb_id, user["id"]),
    )
    database.run(
        "INSERT INTO graph_document_states VALUES(?,?, 'build',?,'ready','model','v1','now',NULL,'now')",
        (kb_id, document_id, "a" * 64),
    )
    for entity_id, name in (("entity-a", "Alice"), ("entity-b", "Bob")):
        database.run(
            "INSERT INTO entities VALUES(?,?,?,?,?,?,?)",
            (entity_id, kb_id, name, name.lower(), "person", "now", "now"),
        )
    database.run("INSERT INTO entity_aliases VALUES('alias','entity-a','alice')")
    database.run(
        "INSERT INTO relations VALUES('relation',?,?,?, ?,0.9,'model','v1','now','now')",
        (kb_id, "entity-a", "knows", "entity-b"),
    )
    database.run(
        "INSERT INTO entity_mentions VALUES('mention','entity-a',?,?, 'doc:0',0,5)",
        (kb_id, document_id),
    )
    database.run(
        "INSERT INTO relation_mentions VALUES('relation-mention','relation',?,?, 'doc:0','build')",
        (kb_id, document_id),
    )

    store.cleanup_document(knowledge_base_id=kb_id, document_id=document_id)

    assert database.one("SELECT 1 FROM graph_document_states") is None
    assert database.one("SELECT 1 FROM relation_mentions") is None
    assert database.one("SELECT 1 FROM entity_mentions") is None
    assert database.one("SELECT 1 FROM relations") is None
    assert database.one("SELECT 1 FROM entities") is None
