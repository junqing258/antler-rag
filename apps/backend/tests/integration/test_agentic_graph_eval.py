"""Stable, synthetic retrieval baseline for later vector/hybrid/agent comparisons."""

from __future__ import annotations

import json
from pathlib import Path

from rag.retrieval import Evidence, RetrievalFilters, RetrievalService


class FixedCorpusRetriever:
    name = "vector"

    def __init__(self) -> None:
        self.calls = 0
        self.by_query = {
            "退款期限是多少天？": ["policy:0", "policy:1"],
            "谁批准例外退款？": ["policy:1", "roles:0"],
            "高级审批人属于哪个团队？": ["roles:1", "teams:0"],
            "总部停车费是多少？": ["policy:0"],
            "Mercury 的负责人是谁？": ["mercury-project:0", "mercury-product:0"],
        }

    def retrieve(self, *, query: str, filters: RetrievalFilters) -> list[Evidence]:
        self.calls += 1
        return [
            Evidence(
                evidence_id=f"vector:{chunk_id}",
                knowledge_base_id="eval-kb",
                document_id=chunk_id.split(":")[0],
                chunk_id=chunk_id,
                chunk_index=int(chunk_id.rsplit(":", 1)[1]),
                filename="synthetic.md",
                content=f"Synthetic evidence for {chunk_id}",
                source_type="vector",
                score=1 - index / 10,
            )
            for index, chunk_id in enumerate(self.by_query[query])
        ]


def test_synthetic_eval_baseline_records_retrieval_quality_without_llm() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "agentic_graph_eval.jsonl"
    cases = [json.loads(line) for line in fixture.read_text().splitlines() if line]
    retriever = FixedCorpusRetriever()
    service = RetrievalService(retriever)

    reciprocal_ranks: list[float] = []
    recalls: list[float] = []
    citation_precisions: list[float] = []
    for case in cases:
        results = service.retrieve(knowledge_base_id="eval-kb", query=case["query"], top_k=3)
        found = [result.chunk_id for result in results]
        expected = set(case["expected_chunk_ids"])
        recalls.append(1.0 if not expected else len(expected & set(found)) / len(expected))
        first_expected_rank = next(
            (index for index, item in enumerate(found, 1) if item in expected), None
        )
        reciprocal_ranks.append(0.0 if first_expected_rank is None else 1 / first_expected_rank)
        cited = set(found) & set(case["expected_citation_chunk_ids"])
        citation_precisions.append(1.0 if not found else len(cited) / len(found))

    metrics = {
        "recall_at_3": sum(recalls) / len(recalls),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "citation_precision": sum(citation_precisions) / len(citation_precisions),
        "llm_calls": 0,
        "retriever_calls": retriever.calls,
    }
    assert metrics == {
        "recall_at_3": 1.0,
        "mrr": 0.8,
        "citation_precision": 0.7,
        "llm_calls": 0,
        "retriever_calls": 5,
    }
