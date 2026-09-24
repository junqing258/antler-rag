from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from config import Settings


def test_agentic_endpoint_is_disabled_by_default(tmp_path: Path) -> None:
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
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        knowledge_base = client.post(
            "/api/v1/knowledge-bases", json={"name": "Test KB"}, headers=headers
        ).json()
        response = client.post(
            "/api/v1/agentic-rag",
            json={"knowledge_base_id": knowledge_base["id"], "message": "test"},
            headers=headers,
        )

    assert response.status_code == 503
    assert response.json()["code"] == "feature_disabled"


def test_agentic_endpoint_requires_its_dedicated_api_key_scope(tmp_path: Path) -> None:
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
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        knowledge_base = client.post(
            "/api/v1/knowledge-bases", json={"name": "Test KB"}, headers=headers
        ).json()
        retrieve_key = client.post(
            "/api/v1/api-keys", json={"name": "retrieve", "scopes": ["retrieve"]}, headers=headers
        ).json()["api_key"]
        agentic_key = client.post(
            "/api/v1/api-keys",
            json={"name": "agentic", "scopes": ["agentic:query"]},
            headers=headers,
        ).json()["api_key"]
        payload = {"knowledge_base_id": knowledge_base["id"], "message": "test"}
        forbidden = client.post(
            "/api/v1/agentic-rag", json=payload, headers={"X-API-Key": retrieve_key}
        )
        allowed = client.post(
            "/api/v1/agentic-rag", json=payload, headers={"X-API-Key": agentic_key}
        )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "insufficient_scope"
    assert allowed.status_code == 503
    assert allowed.json()["code"] == "feature_disabled"
