from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import httpx

from core.config import Settings
from services.errors import APIError


async def generate_answer(
    *,
    settings: Settings,
    prompt: str,
    question: str,
    chunks: list[Any],
    request_id: str,
    logger: logging.Logger,
) -> str:
    """Call the configured OpenAI-compatible chat service for retrieved context."""
    source_text = "\n\n".join(
        f"[Source {index}: {chunk.filename}]\n{chunk.content}"
        for index, chunk in enumerate(chunks, 1)
    )
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                json={
                    "model": settings.chat_model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": f"Sources:\n{source_text}\n\nQuestion: {question}",
                        },
                    ],
                    "temperature": 0,
                },
                headers=headers,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, TypeError, IndexError) as error:
        status_code = (
            error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        )
        logger.warning(
            "chat_request_failed request_id=%s model=%s status=%s error_type=%s duration_ms=%d",
            request_id,
            settings.chat_model,
            status_code,
            type(error).__name__,
            (perf_counter() - started) * 1000,
        )
        raise APIError("llm_failed", "LLM request failed", 502) from error
    logger.info(
        "chat_request_completed request_id=%s model=%s duration_ms=%d",
        request_id,
        settings.chat_model,
        (perf_counter() - started) * 1000,
    )
    return answer
