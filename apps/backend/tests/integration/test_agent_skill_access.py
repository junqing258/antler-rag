from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from config import Settings


def test_kb_read_scope_allows_api_key_listing_without_changing_session_access(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="a-long-bootstrap-password",
    )
    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "a-long-bootstrap-password"},
        )
        session = {"Authorization": f"Bearer {login.json()['token']}"}
        created = client.post(
            "/api/v1/knowledge-bases", json={"name": "Agent sources"}, headers=session
        ).json()
        read_key = client.post(
            "/api/v1/api-keys", json={"name": "kb list", "scopes": ["kb:read"]}, headers=session
        ).json()["api_key"]
        other_key = client.post(
            "/api/v1/api-keys", json={"name": "retrieve", "scopes": ["retrieve"]}, headers=session
        ).json()["api_key"]

        session_response = client.get("/api/v1/knowledge-bases", headers=session)
        allowed = client.get("/api/v1/knowledge-bases", headers={"X-API-Key": read_key})
        forbidden = client.get("/api/v1/knowledge-bases", headers={"X-API-Key": other_key})

    assert session_response.status_code == 200
    assert allowed.status_code == 200
    assert [item["id"] for item in allowed.json()["items"]] == [created["id"]]
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "insufficient_scope"
