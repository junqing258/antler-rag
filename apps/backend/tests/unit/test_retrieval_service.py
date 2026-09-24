from rag.retrieval import Evidence, RetrievalFilters, RetrievalService, VectorRetriever
from rag.store import RetrievedChunk


class FakeStore:
    def __init__(self) -> None:
        self.received: dict[str, object] | None = None

    def retrieve(self, **kwargs: object) -> list[RetrievedChunk]:
        self.received = kwargs
        return [
            RetrievedChunk(
                chunk_id="doc:0",
                document_id="doc",
                knowledge_base_id="kb",
                filename="doc.md",
                content="first",
                distance=0.2,
                chunk_index=0,
            )
        ]


class DuplicateRetriever:
    name = "vector"

    def retrieve(self, *, query: str, filters: RetrievalFilters) -> list[Evidence]:
        first = Evidence(
            evidence_id="vector:doc:0",
            knowledge_base_id="kb",
            document_id="doc",
            chunk_id="doc:0",
            chunk_index=0,
            filename="doc.md",
            content="first",
            source_type="vector",
            score=0.8,
        )
        return [
            first,
            first,
            Evidence(
                evidence_id="vector:doc:1",
                knowledge_base_id="kb",
                document_id="doc",
                chunk_id="doc:1",
                chunk_index=1,
                filename="doc.md",
                content="second",
                source_type="vector",
                score=0.7,
            ),
        ]


def test_vector_retriever_preserves_legacy_store_arguments_and_provenance() -> None:
    store = FakeStore()
    service = RetrievalService(VectorRetriever(store))  # type: ignore[arg-type]

    evidence = service.retrieve(
        knowledge_base_id="kb",
        query="question",
        top_k=2,
        document_ids=["doc", "doc"],
        score_threshold=0.5,
        rerank=True,
    )

    assert store.received == {
        "knowledge_base_id": "kb",
        "query": "question",
        "top_k": 2,
        "document_ids": ["doc"],
        "score_threshold": 0.5,
        "rerank": True,
    }
    assert evidence[0].evidence_id == "vector:doc:0"
    assert evidence[0].score == 0.8
    assert evidence[0].source_type == "vector"


def test_service_deduplicates_chunks_without_changing_first_result_order() -> None:
    service = RetrievalService(DuplicateRetriever())

    evidence, trace = service.search(
        query="question", filters=RetrievalFilters.create(knowledge_base_id="kb", top_k=2)
    )

    assert [item.chunk_id for item in evidence] == ["doc:0", "doc:1"]
    assert trace.mode == "vector"
    assert trace.candidate_count == 3
    assert trace.result_count == 2
