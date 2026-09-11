from pathlib import Path

import pytest

from antler_rag.db import Database


def test_tenant_owned_queries_do_not_cross_tenants(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.migrate()
    first, second = db.create_tenant("A"), db.create_tenant("B")
    user = db.create_user("member@example.com", "hash", "2099-01-01T00:00:00+00:00")
    first_member = db.add_member(first["id"], user["id"], "viewer")

    assert db.member_by_id(second["id"], first_member["id"]) is None
    assert db.membership(first["id"], user["id"])["role"] == "viewer"
    assert db.membership(second["id"], user["id"]) is None


def test_last_active_platform_admin_cannot_be_revoked(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.sqlite3")
    db.migrate()
    db.bootstrap_admin("admin@example.com", "hash")
    admin = db.user_by_email("admin@example.com")
    assert admin
    with pytest.raises(ValueError, match="last active"):
        db.set_platform_admin(admin["id"], False)
