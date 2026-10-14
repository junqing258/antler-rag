import json

import httpx
import pytest

from rag.store import OpenAICompatibleEmbeddingFunction


def test_openai_compatible_embedding_function_orders_vectors_by_index() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["authorization"] = request.headers["Authorization"]
        received["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    function = OpenAICompatibleEmbeddingFunction(
        base_url="https://example.test/v1/",
        api_key="test-key",
        model="text-embedding-v4",
        dimensions=1024,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    vectors = function(["first", "second"])
    assert vectors[0].tolist() == pytest.approx([0.1, 0.2])
    assert vectors[1].tolist() == pytest.approx([0.3, 0.4])
    assert received == {
        "url": "https://example.test/v1/embeddings",
        "authorization": "Bearer test-key",
        "payload": {
            "model": "text-embedding-v4",
            "input": ["first", "second"],
            "dimensions": 1024,
        },
    }


def test_openai_compatible_embedding_function_rejects_invalid_response() -> None:
    function = OpenAICompatibleEmbeddingFunction(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="text-embedding-v4",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
        ),
    )

    with pytest.raises(ValueError, match="invalid response"):
        function(["first"])


def test_openai_compatible_embedding_function_batches_large_inputs() -> None:
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        requests.append(texts)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(text)]} for index, text in enumerate(texts)
                ]
            },
        )

    function = OpenAICompatibleEmbeddingFunction(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="text-embedding-v4",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    vectors = function([str(index) for index in range(11)])

    assert requests == [[str(index) for index in range(10)], ["10"]]
    assert [vector.tolist() for vector in vectors] == [[float(index)] for index in range(11)]


def test_index_drafts_writes_current_strategy_metadata_without_changing_content():
    from rag.chunking import CHUNKER_VERSIONS, ChunkDraft, chunk_recursive
    from rag.store import RAGStore

    class Collection:
        def add(self, **payload):
            self.payload = payload

    store = object.__new__(RAGStore)
    store.collection = Collection()
    for strategy, drafts in (
        ("recursive", chunk_recursive("# Heading\n\nBody", chunk_size=100, chunk_overlap=20)),
        (
            "structure",
            [
                ChunkDraft(
                    content="  exact text\n",
                    heading_path=["Heading"],
                    section_id="s000001",
                    structure_quality="headings",
                )
            ],
        ),
    ):
        assert store.index_drafts(
            knowledge_base_id="kb",
            document_id="doc",
            filename="a.md",
            drafts=drafts,
            digest="sha",
            chunk_strategy=strategy,
        ) == len(drafts)
        assert store.collection.payload["documents"] == [draft.content for draft in drafts]
        metadata = store.collection.payload["metadatas"][0]
        assert (
            metadata["chunk_strategy"] == strategy
            and metadata["chunker_version"] == CHUNKER_VERSIONS[strategy]
        )
        assert json.loads(metadata["heading_path_json"]) == drafts[0].heading_path
        if strategy == "recursive":
            assert "section_id" not in metadata and "structure_quality" not in metadata


@pytest.mark.parametrize("missing", ["chunk_strategy", "chunker_version", "heading_path_json"])
def test_stored_chunks_require_current_metadata(missing):
    from rag.chunking import ChunkMetadata

    metadata = {
        "chunk_strategy": "recursive",
        "chunker_version": "recursive-v1",
        "heading_path_json": "[]",
    }
    del metadata[missing]
    with pytest.raises(KeyError):
        ChunkMetadata.from_chroma(metadata)


def test_stored_chunks_reject_unsupported_chunker_or_malformed_heading_path():
    from rag.chunking import ChunkMetadata

    with pytest.raises(ValueError, match="current chunker"):
        ChunkMetadata.from_chroma(
            {
                "chunk_strategy": "structure",
                "chunker_version": "structure-v0",
                "heading_path_json": "[]",
            }
        )
    with pytest.raises(ValueError, match="heading_path_json"):
        ChunkMetadata.from_chroma(
            {
                "chunk_strategy": "recursive",
                "chunker_version": "recursive-v1",
                "heading_path_json": "{}",
            }
        )
