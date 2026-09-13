import json

import httpx
import pytest

from rag.store import RAGStore, RerankerError, TEIReranker


class FakeCollection:
    def __init__(self) -> None:
        self.n_results: int | None = None

    def query(self, **kwargs: object) -> dict[str, list[list[object]]]:
        self.n_results = kwargs["n_results"]  # type: ignore[assignment]
        return {
            "ids": [["doc:0", "doc:1", "doc:2"]],
            "documents": [["first", "second", "third"]],
            "metadatas": [
                [
                    {
                        "document_id": "doc",
                        "knowledge_base_id": "kb",
                        "filename": "a.md",
                        "chunk_index": 0,
                    },
                    {
                        "document_id": "doc",
                        "knowledge_base_id": "kb",
                        "filename": "a.md",
                        "chunk_index": 1,
                    },
                    {
                        "document_id": "doc",
                        "knowledge_base_id": "kb",
                        "filename": "a.md",
                        "chunk_index": 2,
                    },
                ]
            ],
            "distances": [[0.1, 0.4, 0.8]],
        }


class FakeReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, documents: list[str]) -> list[float]:
        self.calls.append((query, documents))
        return [0.1, 0.9, 0.5]


def make_store(reranker: FakeReranker | None = None) -> tuple[RAGStore, FakeCollection]:
    store = RAGStore.__new__(RAGStore)
    collection = FakeCollection()
    store.collection = collection  # type: ignore[assignment]
    store.reranker = reranker
    return store, collection


def test_retrieve_filters_by_cosine_similarity_threshold() -> None:
    store, collection = make_store()

    chunks = store.retrieve(knowledge_base_id="kb", query="question", top_k=3, score_threshold=0.6)

    assert collection.n_results == 3
    assert [chunk.content for chunk in chunks] == ["first", "second"]


def test_retrieve_reranks_larger_candidate_set_and_preserves_score() -> None:
    reranker = FakeReranker()
    store, collection = make_store(reranker)

    chunks = store.retrieve(knowledge_base_id="kb", query="question", top_k=2, rerank=True)

    assert collection.n_results == 8
    assert reranker.calls == [("question", ["first", "second", "third"])]
    assert [chunk.content for chunk in chunks] == ["second", "third"]
    assert [chunk.rerank_score for chunk in chunks] == [0.9, 0.5]


def test_retrieve_rejects_reranking_when_no_model_is_configured() -> None:
    store, _ = make_store()

    with pytest.raises(RerankerError, match="RAG_RERANKER_BASE_URL"):
        store.retrieve(knowledge_base_id="kb", query="question", top_k=2, rerank=True)


def test_tei_reranker_restores_scores_to_candidate_order() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["authorization"] = request.headers["Authorization"]
        received["payload"] = json.loads(request.content)
        return httpx.Response(200, json=[{"index": 1, "score": 0.8}, {"index": 0, "score": 0.2}])

    reranker = TEIReranker(
        base_url="https://reranker.example.test/",
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert reranker.score("question", ["first", "second"]) == [0.2, 0.8]
    assert received == {
        "url": "https://reranker.example.test/rerank",
        "authorization": "Bearer test-key",
        "payload": {"query": "question", "texts": ["first", "second"]},
    }
