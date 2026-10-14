from pathlib import Path

import pytest

from db import Database


def test_bootstrap_creates_global_admin_without_default_knowledge_base(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.initialize()
    assert db.initialize() is None
    assert db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin and admin["role"] == "admin"
    assert db.knowledge_bases() == []


def test_last_active_admin_cannot_be_downgraded_or_disabled(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.initialize()
    db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin
    with pytest.raises(ValueError, match="last active"):
        db.update_user(admin["id"], "viewer", None)
    with pytest.raises(ValueError, match="last active"):
        db.update_user(admin["id"], None, "disabled")


@pytest.mark.parametrize("stale_status", ["deleted", "failed"])
def test_reupload_reuses_a_deleted_or_failed_document_record(
    tmp_path: Path, stale_status: str
) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.initialize()
    db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin
    knowledge_base = db.create_knowledge_base("Knowledge Base", "", 900, 150)
    first = db.create_document(
        knowledge_base["id"], "old.pdf", "old.pdf", "a" * 64, 10, admin["id"]
    )
    db.set_document_status(knowledge_base["id"], first["id"], stale_status, 3, "Old failure")

    reuploaded = db.create_document(
        knowledge_base["id"], "new.pdf", "new.pdf", "a" * 64, 20, admin["id"]
    )

    assert reuploaded["id"] == first["id"]
    assert reuploaded["filename"] == "new.pdf"
    assert reuploaded["stored_filename"] == "new.pdf"
    assert reuploaded["size_bytes"] == 20
    assert reuploaded["chunk_count"] == 0
    assert reuploaded["status"] == "pending"
    assert reuploaded["error_message"] is None
