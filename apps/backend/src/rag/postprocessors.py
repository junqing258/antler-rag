"""先做显式的原始距离阈值过滤，再做稳定的 TEI 重排。"""

import math
from collections.abc import Sequence
from time import perf_counter
from typing import Any, Protocol

import httpx
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from loguru import logger
from pydantic import PrivateAttr

from .execution import remaining_timeout


class RerankerError(RuntimeError):
    """请求的 reranker 无法使用时抛出。"""


class Reranker(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class TEIReranker:
    """通过 Hugging Face Text Embeddings Inference 的 /rerank API 做 CrossEncoder 重排。"""

    def __init__(
        self, *, base_url: str, api_key: str | None = None, client: httpx.Client | None = None
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10))

    def close(self) -> None:
        self.client.close()

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        started = perf_counter()
        try:
            response = self.client.post(
                f"{self.base_url}/rerank",
                headers=headers,
                json={"query": query, "texts": list(documents)},
                timeout=remaining_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            logger.warning(
                "reranker_request_failed candidates={candidates} error_type={error_type} "
                "duration_ms={duration_ms:.0f}",
                candidates=len(documents),
                error_type=type(error).__name__,
                duration_ms=(perf_counter() - started) * 1000,
            )
            raise RerankerError("Reranker request failed") from error
        if not isinstance(payload, list):
            raise RerankerError("Reranker returned an invalid response")
        scores: list[float | None] = [None] * len(documents)
        try:
            for item in payload:
                index = item["index"]
                if (
                    type(index) is not int
                    or not 0 <= index < len(documents)
                    or scores[index] is not None
                ):
                    raise ValueError
                scores[index] = float(item["score"])
                if not math.isfinite(scores[index]):
                    raise ValueError
        except (KeyError, TypeError, ValueError) as error:
            raise RerankerError("Reranker returned an invalid response") from error
        if any(score is None for score in scores):
            raise RerankerError("Reranker returned an incomplete response")
        return [float(score) for score in scores]


class CandidatePostprocessor(BaseNodePostprocessor):
    threshold: float | None = None
    top_k: int
    _reranker: Any = PrivateAttr(default=None)

    def __init__(self, *, top_k, threshold=None, reranker=None):
        super().__init__(top_k=top_k, threshold=threshold)
        self._reranker = reranker

    def _postprocess_nodes(self, nodes, query_bundle=None):
        if self.threshold is not None:
            nodes = [
                item
                for item in nodes
                if (0.0 if item.score is None else max(0, min(1, 1 - item.score))) >= self.threshold
            ]
        if self._reranker is not None and nodes:
            scores = self._reranker.score(
                query_bundle.query_str, [item.node.text for item in nodes]
            )
            for item, score in zip(nodes, scores, strict=True):
                item.node.metadata["_rerank_score"] = score
            nodes = sorted(
                nodes, key=lambda item: item.node.metadata["_rerank_score"], reverse=True
            )
        return nodes[: self.top_k]
