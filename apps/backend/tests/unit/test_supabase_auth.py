import httpx
import pytest

from core.config import Settings
from db import Database
from routers.dependencies import access, verified_user
from services.errors import APIError
from utils.security import token_digest


@pytest.fixture
def context(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        supabase_url="https://auth.test",
        supabase_publishable_key="public",
        bootstrap_admin_email="admin@test.com",
    )
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    identity = {
        "id": "supabase-user-id",
        "email": "admin@test.com",
        "email_confirmed_at": "2026-01-01",
    }

    def get(url, **kwargs):
        assert url == "https://auth.test/auth/v1/user"
        assert kwargs["headers"]["Authorization"] == "Bearer valid"
        return httpx.Response(200, json=identity, request=httpx.Request("GET", url))

    monkeypatch.setattr("routers.dependencies.httpx.get", get)
    return settings, database, identity


def test_verified_identity_and_roles(context):
    settings, database, identity = context
    user = verified_user("valid", database, settings)
    assert user["id"] == identity["id"]
    assert user["role"] == "admin"
    assert user["password_hash"] == "!supabase"
    assert database.many("SELECT * FROM sessions") == []
    identity.update(id="viewer-id", email="viewer@test.com")
    assert verified_user("valid", database, settings)["role"] == "viewer"
    with pytest.raises(APIError) as error:
        access(roles={"admin"})(None, "Bearer valid", database, settings)
    assert error.value.status_code == 403


def test_disabled_account_stays_disabled(context):
    settings, database, _ = context
    user = verified_user("valid", database, settings)
    database.run("UPDATE users SET status='disabled' WHERE id=?", (user["id"],))
    with pytest.raises(APIError) as error:
        verified_user("valid", database, settings)
    assert error.value.code == "account_disabled"


def test_unverified_email_rejected(context):
    settings, database, identity = context
    identity["email_confirmed_at"] = None
    with pytest.raises(APIError) as error:
        verified_user("valid", database, settings)
    assert error.value.code == "invalid_session"
    assert database.users() == []


@pytest.mark.parametrize(
    "status,code", [(401, "invalid_session"), (403, "invalid_session"), (500, "auth_unavailable")]
)
def test_invalid_or_unavailable_auth(context, monkeypatch, status, code):
    settings, database, _ = context
    monkeypatch.setattr(
        "routers.dependencies.httpx.get",
        lambda *a, **k: httpx.Response(status, request=httpx.Request("GET", "https://auth.test")),
    )
    with pytest.raises(APIError) as error:
        verified_user("forged", database, settings)
    assert error.value.code == code
    assert database.users() == []


def test_legacy_email_is_not_linked(context):
    settings, database, _ = context
    database.bootstrap_admin("admin@test.com", "legacy")
    with pytest.raises(APIError) as error:
        verified_user("valid", database, settings)
    assert error.value.code == "account_conflict"


def test_api_key_still_works_without_supabase(context):
    settings, database, _ = context
    user = verified_user("valid", database, settings)
    database.create_api_key("test", "ark_test", token_digest("key"), ["retrieve"], None, user["id"])
    principal = access("retrieve")("key", None, database, Settings(_env_file=None))
    assert principal.actor_type == "api_key"


def test_missing_config_fails_closed(context):
    _, database, _ = context
    with pytest.raises(APIError) as error:
        verified_user("legacy", database, Settings(_env_file=None))
    assert error.value.code == "auth_unavailable"
