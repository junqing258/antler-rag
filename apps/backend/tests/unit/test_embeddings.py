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
            json={"data": [{"index": index, "embedding": [float(text)]} for index, text in enumerate(texts)]},
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
