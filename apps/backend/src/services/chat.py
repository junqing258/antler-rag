from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx

from core.config import Settings
from rag.llm import CompatibleLLM, completion
from rag.synthesis import answer_messages
from services.errors import APIError


async def generate_answer(
    *,
    settings: Settings,
    prompt: str,
    question: str,
    chunks: list[Any],
    request_id: str,
    logger: Any,
) -> str:
    """Call the configured OpenAI-compatible chat service for retrieved context."""
    started = perf_counter()
    try:
        answer = await completion(
            CompatibleLLM(settings), answer_messages(prompt, question, chunks)
        )
    except (httpx.HTTPError, KeyError, TypeError, IndexError, ValueError) as error:
        status_code = (
            error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        )
        logger.warning(
            "chat_request_failed request_id={request_id} model={model} status={status} "
            "error_type={error_type} duration_ms={duration_ms:.0f}",
            request_id=request_id,
            model=settings.chat_model,
            status=status_code,
            error_type=type(error).__name__,
            duration_ms=(perf_counter() - started) * 1000,
        )
        raise APIError("llm_failed", "LLM request failed", 502) from error
    logger.info(
        "chat_request_completed request_id={request_id} model={model} duration_ms={duration_ms:.0f}",
        request_id=request_id,
        model=settings.chat_model,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return answer
