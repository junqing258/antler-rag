"""HTTP tests always use local deterministic embeddings, regardless of .env."""

import hashlib
import json

import httpx
import pytest

import app
import rag.store
from core.config import Settings
from rag.store import OpenAICompatibleEmbeddingFunction, RAGStore


@pytest.fixture(autouse=True)
def isolated_embedding_store(monkeypatch):
    class LocalEmbedding(OpenAICompatibleEmbeddingFunction):
        def __init__(self, **kwargs):
            def handle(request):
                vectors = []
                for index, text in enumerate(json.loads(request.content)["input"]):
                    vector = [0.0] * 32
                    for character in text:
                        vector[hashlib.sha256(character.encode()).digest()[0] % 32] += 1.0
                    vectors.append({"index": index, "embedding": vector})
                return httpx.Response(200, json={"data": vectors})

            kwargs["client"] = httpx.Client(transport=httpx.MockTransport(handle))
            super().__init__(**kwargs)

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setattr(rag.store, "OpenAICompatibleEmbeddingFunction", LocalEmbedding)

    def local_store(settings):
        return RAGStore(
            settings.model_copy(
                update={
                    "embedding_model": "test-local",
                    "llm_base_url": "https://embedding.test/v1",
                    "llm_api_key": "test-only",
                    "embedding_dimensions": 32,
                    "reranker_base_url": None,
                }
            )
        )

    monkeypatch.setattr(app, "RAGStore", local_store)
