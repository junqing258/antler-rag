"""可复现的证据/上下文冒烟对比；不是语义质量基准。"""

import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from fastapi.testclient import TestClient

from app import create_app
from core.config import Settings


def test_fixed_handbook_questions_compare_evidence_and_record_cost(tmp_path):
    content = (Path(__file__).parents[1] / "fixtures/structure_handbook.md").read_bytes()
    cases = [
        ("年假申请需要提前多久？", "提前三个工作日"),
        ("病假需要提供什么？", "提供相关证明"),
        ("报销发票何时提交？", "二十五日前"),
    ]
    application = create_app(
        Settings(
            _env_file=None,
            data_dir=tmp_path,
            bootstrap_admin_email="admin@example.com",
        )
    )
    report = {
        "fixture": "structure_handbook.md",
        "embedding": "deterministic character hash stub",
        "top_k": 1,
        "strategies": {},
    }
    with TestClient(application) as client:
        token = "test-admin"
        headers = {"Authorization": f"Bearer {token}"}
        for strategy in ("recursive", "structure"):
            kb = client.post(
                "/api/v1/knowledge-bases",
                headers=headers,
                json={"name": strategy, "chunk_strategy": strategy},
            ).json()
            endpoint = f"/api/v1/knowledge-bases/{kb['id']}/documents"
            started = perf_counter()
            document = client.post(
                endpoint,
                headers=headers,
                files={"files": ("handbook.md", content, "text/markdown")},
            ).json()["documents"][0]
            elapsed = (perf_counter() - started) * 1000
            chunks = client.get(f"{endpoint}/{document['id']}/chunks", headers=headers).json()[
                "items"
            ]
            lengths = [len(chunk["content"]) for chunk in chunks]
            found = []
            for query, expected in cases:
                results = client.post(
                    "/api/v1/retrieve",
                    headers=headers,
                    json={"knowledge_base_id": kb["id"], "query": query, "top_k": 1},
                ).json()["results"]
                found.append(
                    {
                        "question": query,
                        "expected_fact_found": any(
                            expected in result["content"] for result in results
                        ),
                        "heading_paths": [result["heading_path"] for result in results],
                    }
                )
            report["strategies"][strategy] = {
                "chunks": len(chunks),
                "length_min": min(lengths),
                "length_mean": mean(lengths),
                "length_max": max(lengths),
                "index_ms": round(elapsed, 2),
                "fact_recall_at_1": sum(case["expected_fact_found"] for case in found) / len(cases),
                "questions": found,
            }
    assert report["strategies"]["recursive"]["chunks"] == 1
    assert report["strategies"]["structure"]["chunks"] == 4
    assert report["strategies"]["structure"]["length_max"] <= 900
    print("STRUCTURE_EVAL " + json.dumps(report, ensure_ascii=False))
