from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import create_app
from core.config import Settings


def test_kb_read_scope_allows_api_key_listing_without_changing_session_access(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        bootstrap_admin_email="admin@example.com",
    )
    with TestClient(create_app(settings)) as client:
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer test-admin"}
            ).status_code
            == 200
        )
        session = {"Authorization": "Bearer test-admin"}
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


def test_agent_skill_download_contains_installable_files_and_requires_admin(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        bootstrap_admin_email="admin@example.com",
    )
    with TestClient(create_app(settings)) as client:
        denied = client.get("/api/v1/agent-skill/download")
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer test-admin"}
            ).status_code
            == 200
        )
        session = {"Authorization": "Bearer test-admin"}
        downloaded = client.get("/api/v1/agent-skill/download", headers=session)

    assert denied.status_code == 401
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(downloaded.content)) as package:
        assert set(package.namelist()) == {
            "antler-rag/SKILL.md",
            "antler-rag/scripts/rag.py",
        }
        assert b"name: antler-rag" in package.read("antler-rag/SKILL.md")
