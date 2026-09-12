from pathlib import Path

from fastapi.testclient import TestClient

from antler_rag.app import create_app
from antler_rag.config import Settings


def login(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "a-long-bootstrap-password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_global_api_requires_no_tenant_header_and_tenant_routes_are_gone(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, bootstrap_admin_email="admin@example.com", bootstrap_admin_password="a-long-bootstrap-password")
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        created = client.post("/api/v1/knowledge-bases", json={"name": "Global"}, headers=headers)
        assert created.status_code == 201
        assert client.get("/api/v1/knowledge-bases", headers=headers).status_code == 200
        assert client.get("/api/v1/tenants", headers=headers).status_code == 404
        assert client.get("/api/v1/auth/me/tenants", headers=headers).status_code == 404


def test_last_active_admin_protection_is_exposed_by_api(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, bootstrap_admin_email="admin@example.com", bootstrap_admin_password="a-long-bootstrap-password")
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        user = client.get("/api/v1/users", headers=headers).json()["items"][0]
        response = client.patch(f"/api/v1/users/{user['id']}", json={"role": "viewer"}, headers=headers)
        assert response.status_code == 409
        assert response.json()["code"] == "last_active_admin"


def test_retrieve_reports_when_requested_reranker_is_not_configured(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, bootstrap_admin_email="admin@example.com", bootstrap_admin_password="a-long-bootstrap-password")
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        knowledge_base = client.post("/api/v1/knowledge-bases", json={"name": "Global"}, headers=headers).json()
        response = client.post(
            "/api/v1/retrieve",
            json={"knowledge_base_id": knowledge_base["id"], "query": "test", "rerank": True},
            headers=headers,
        )

    assert response.status_code == 503
    assert response.json()["code"] == "reranker_unavailable"
