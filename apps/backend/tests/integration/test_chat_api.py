from pathlib import Path

from fastapi.testclient import TestClient

from antler_rag.app import create_app
from antler_rag.config import Settings


def test_chat_accepts_message_body_field(tmp_path: Path) -> None:
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
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {login.json()['token']}"},
            json={
                "knowledge_base_id": "missing-knowledge-base",
                "message": "Agent 工具有哪些分类",
                "top_k": 5,
            },
        )

    # A parsed request reaches the business check; a missing `query` would return 422 instead.
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
