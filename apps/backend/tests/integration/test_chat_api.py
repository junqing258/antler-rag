from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from core.config import Settings


def test_chat_accepts_message_body_field(tmp_path: Path) -> None:
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
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": "Bearer test-admin"},
            json={
                "knowledge_base_id": "missing-knowledge-base",
                "message": "Agent 工具有哪些分类",
                "top_k": 5,
            },
        )

    # A parsed request reaches the business check; a missing `query` would return 422 instead.
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
