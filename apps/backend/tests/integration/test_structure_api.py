from fastapi.testclient import TestClient

from app import create_app
from core.config import Settings


def test_structure_configuration_pagination_scopes_and_source_metadata(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        bootstrap_admin_email="admin@example.com",
    )
    application = create_app(settings)
    with TestClient(application) as client:
        token = "test-admin"
        headers = {"Authorization": f"Bearer {token}"}
        kb = client.post(
            "/api/v1/knowledge-bases",
            headers=headers,
            json={
                "name": "Structure",
                "chunk_strategy": "structure",
                "chunk_size": 100,
                "chunk_overlap": 20,
            },
        ).json()
        assert kb["chunk_strategy"] == "structure"
        other = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Recursive"}
        ).json()
        assert other["chunk_strategy"] == "recursive"
        for payload in (
            {"name": "Unknown", "chunk_strategy": "semantic"},
            {"name": "Overlap", "chunk_size": 100, "chunk_overlap": 100},
        ):
            assert (
                client.post("/api/v1/knowledge-bases", headers=headers, json=payload).status_code
                == 422
            )
        base = f"/api/v1/knowledge-bases/{kb['id']}/documents"
        response = client.post(
            base,
            headers=headers,
            files={
                "files": (
                    "leave.md",
                    "# 员工手册\n## 年假\n提前三个工作日。\n## 病假\n提供证明。".encode(),
                    "text/markdown",
                )
            },
        )
        assert response.status_code == 201, response.text
        doc = response.json()["documents"][0]
        endpoint = f"{base}/{doc['id']}/chunks"
        first = client.get(endpoint, headers=headers, params={"limit": 1}).json()
        second = client.get(endpoint, headers=headers, params={"offset": 1, "limit": 1}).json()
        assert first["total"] == second["total"] == 2
        assert first["items"][0]["chunk_index"] == 0 and second["items"][0]["chunk_index"] == 1
        chunk = first["items"][0]
        assert chunk["heading_path"] == ["员工手册", "年假"]
        assert chunk["chunk_strategy"] == "structure" and chunk["chunker_version"] == "structure-v1"
        assert chunk["structure_quality"] == "headings" and chunk["page_start"] is None
        assert client.get(endpoint, headers=headers, params={"offset": 10}).json() == {
            "items": [],
            "total": 2,
        }
        assert "chunks" not in client.get(f"{base}/{doc['id']}", headers=headers).json()
        assert (
            client.get(
                f"/api/v1/knowledge-bases/{other['id']}/documents/{doc['id']}/chunks",
                headers=headers,
            ).status_code
            == 404
        )
        for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
            assert client.get(endpoint, headers=headers, params=params).status_code == 422
        for scope, status in (("retrieve", 403), ("documents:read", 200)):
            key = client.post(
                "/api/v1/api-keys", headers=headers, json={"name": scope, "scopes": [scope]}
            ).json()["api_key"]
            assert client.get(endpoint, headers={"X-API-Key": key}).status_code == status
        retrieved = client.post(
            "/api/v1/retrieve",
            headers=headers,
            json={"knowledge_base_id": kb["id"], "query": "年假", "top_k": 2},
        ).json()
        assert set(retrieved) == {"results"}
        assert any(item["heading_path"] == ["员工手册", "年假"] for item in retrieved["results"])
        chat = client.post(
            "/api/v1/chat",
            headers=headers,
            json={"knowledge_base_id": kb["id"], "message": "年假", "top_k": 2},
        ).json()
        assert "sources" in chat and all(
            source["chunker_version"] == "structure-v1" for source in chat["sources"]
        )
        application.state.db.set_document_status(kb["id"], doc["id"], "indexing")
        assert client.get(endpoint, headers=headers).json() == {"items": [], "total": 0}
        application.state.db.set_knowledge_base_status(kb["id"], "deleted")
        assert client.get(endpoint, headers=headers).status_code == 404


def test_recursive_chunks_have_current_metadata_and_no_invented_structure(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        bootstrap_admin_email="admin@example.com",
    )
    application = create_app(settings)
    with TestClient(application) as client:
        token = "test-admin"
        headers = {"Authorization": f"Bearer {token}"}
        kb = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Recursive"}
        ).json()
        base = f"/api/v1/knowledge-bases/{kb['id']}/documents"
        doc = client.post(
            base, headers=headers, files={"files": ("doc.txt", b"Current content", "text/plain")}
        ).json()["documents"][0]
        item = client.get(f"{base}/{doc['id']}/chunks", headers=headers).json()["items"][0]
        assert (
            item["heading_path"] == []
            and item["structure_quality"] is None
            and item["section_id"] is None
        )
        assert item["chunk_strategy"] == "recursive" and item["chunker_version"] == "recursive-v1"
        result = client.post(
            "/api/v1/retrieve",
            headers=headers,
            json={"knowledge_base_id": kb["id"], "query": "Current content"},
        ).json()["results"][0]
        assert result["heading_path"] == [] and result["chunker_version"] == "recursive-v1"
        assert (
            client.post(
                "/api/v1/chat",
                headers=headers,
                json={"knowledge_base_id": kb["id"], "query": "old field"},
            ).status_code
            == 422
        )
