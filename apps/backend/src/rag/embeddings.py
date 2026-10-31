"""显式接入的 LlamaIndex embeddings；provider 只接收正文文本。"""

from __future__ import annotations

import math
import os
from time import perf_counter
from typing import Any

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings, Space
from llama_index.core.embeddings import BaseEmbedding
from loguru import logger
from pydantic import PrivateAttr

from .execution import remaining_timeout, run_sync

MAX_EMBEDDING_BATCH_SIZE = 10


def validate_vectors(vectors, count, dimensions=None):
    if len(vectors) != count:
        raise ValueError("Embedding provider returned an invalid response count")
    width = dimensions or (len(vectors[0]) if count else 0)
    if any(len(v) != width or not width or any(not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError("Embedding provider returned invalid dimensions or values")


class OpenAICompatibleEmbeddingFunction(EmbeddingFunction[Documents]):
    """通过 OpenAI 兼容的 `/embeddings` 端点生成文本向量。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int | None = None,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        embeddings: Embeddings = []
        for start in range(0, len(input), MAX_EMBEDDING_BATCH_SIZE):
            embeddings.extend(self._embed_batch(input[start : start + MAX_EMBEDDING_BATCH_SIZE]))
        return embeddings

    def _embed_batch(self, input: Documents) -> Embeddings:
        payload: dict[str, Any] = {"model": self.model, "input": list(input)}
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        started = perf_counter()
        try:
            response = self.client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=remaining_timeout(),
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            status_code = (
                error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
            )
            logger.warning(
                "embedding_request_failed model={model} batch_size={batch_size} status={status} "
                "error_type={error_type} duration_ms={duration_ms:.0f}",
                model=self.model,
                batch_size=len(input),
                status=status_code,
                error_type=type(error).__name__,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise
        logger.info(
            "embedding_request_completed model={model} batch_size={batch_size} status={status} "
            "duration_ms={duration_ms:.0f}",
            model=self.model,
            batch_size=len(input),
            status=response.status_code,
            duration_ms=(perf_counter() - started) * 1000,
        )
        data = response.json().get("data")
        if not isinstance(data, list) or len(data) != len(input):
            raise ValueError("Embedding provider returned an invalid response")
        try:
            ordered = sorted(data, key=lambda item: item["index"])
            if any(type(item["index"]) is not int for item in ordered) or [
                item["index"] for item in ordered
            ] != list(range(len(input))):
                raise ValueError("Embedding provider returned invalid indices")
            vectors = [item["embedding"] for item in ordered]
            validate_vectors(vectors, len(input), self.dimensions)
            return vectors
        except (KeyError, TypeError, OverflowError):
            raise ValueError("Embedding provider returned an invalid response") from None

    @staticmethod
    def name() -> str:
        return "openai_compatible"

    def default_space(self) -> Space:
        return "cosine"

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> EmbeddingFunction[Documents]:
        # Chroma 要求的 embedding 配置钩子。密钥由注入的 client 持有。
        return OpenAICompatibleEmbeddingFunction(
            base_url=str(config["base_url"]),
            api_key=os.environ.get("RAG_LLM_API_KEY", ""),
            model=str(config["model"]),
            dimensions=config.get("dimensions"),
        )

    def get_config(self) -> dict[str, Any]:
        # 绝不把 API key 写入 Chroma 的持久化 collection 元数据。
        return {"base_url": self.base_url, "model": self.model, "dimensions": self.dimensions}


class ProviderEmbedding(BaseEmbedding):
    _provider: Any = PrivateAttr()

    def __init__(self, provider):
        super().__init__(model_name="explicit-provider", embed_batch_size=10)
        self._provider = provider

    def _get_text_embeddings(self, texts):
        vectors = [list(map(float, v)) for v in self._provider(texts)]
        validate_vectors(vectors, len(texts))
        return vectors

    def _get_text_embedding(self, text):
        return self._get_text_embeddings([text])[0]

    def _get_query_embedding(self, query):
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query):
        return await run_sync(self._get_query_embedding, query=query)
