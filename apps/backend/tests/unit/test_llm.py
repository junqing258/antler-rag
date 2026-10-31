import asyncio
import json

import httpx
import pytest

from core.config import Settings
from rag.execution import deadline_context
from rag.llm import CompatibleLLM, completion


def test_llm_preserves_wire_contract_and_hides_secrets(monkeypatch):
    received = []

    def handle(request):
        received.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer private-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    llm = CompatibleLLM(
        Settings(
            _env_file=None,
            llm_base_url="https://llm.test/v1",
            llm_api_key="private-key",
            chat_model="service-model",
        )
    )
    assert asyncio.run(completion(llm, [{"role": "user", "content": "question"}])) == "answer"
    assert received == [
        {
            "model": "service-model",
            "messages": [{"role": "user", "content": "question"}],
            "temperature": 0,
        }
    ]
    assert "private-key" not in json.dumps(llm.to_dict())


def test_model_failure_is_not_implicitly_retried(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    llm = CompatibleLLM(
        Settings(_env_file=None, llm_base_url="https://llm.test", chat_model="model")
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(completion(llm, [{"role": "user", "content": "question"}]))
    assert len(calls) == 1


def test_model_call_rejected_after_deadline(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("No HTTP request may start after deadline")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)

    async def scenario():
        token = deadline_context.set(0)
        try:
            with pytest.raises(TimeoutError):
                await completion(CompatibleLLM(Settings(_env_file=None)), [])
        finally:
            deadline_context.reset(token)

    asyncio.run(scenario())
