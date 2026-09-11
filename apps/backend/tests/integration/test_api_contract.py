from pathlib import Path

from fastapi.testclient import TestClient

from antler_rag.app import create_app
from antler_rag.config import Settings


def test_login_and_tenant_header_isolation(tmp_path: Path) -> None:
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
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        tenant = client.post("/api/v1/tenants", json={"name": "Tenant A"}, headers=headers).json()
        headers["X-Tenant-ID"] = tenant["id"]
        assert client.get("/api/v1/knowledge-bases", headers=headers).status_code == 200
        forged = {**headers, "X-Tenant-ID": "not-a-tenant"}
        assert client.get("/api/v1/knowledge-bases", headers=forged).status_code == 404
