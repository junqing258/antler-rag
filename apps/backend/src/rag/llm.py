"""最小可用的 LlamaIndex 兼容 LLM：单次 HTTP 调用，无隐式重试。"""

from collections.abc import Sequence

import httpx
from llama_index.core.llms import (
    ChatMessage,
    ChatResponse,
    CompletionResponse,
    CustomLLM,
    LLMMetadata,
)
from pydantic import PrivateAttr

from .execution import remaining_timeout


class CompatibleLLM(CustomLLM):
    _settings: object = PrivateAttr()
    _model: str = PrivateAttr()

    def __init__(self, settings, model=None):
        super().__init__()
        self._settings = settings
        self._model = model or settings.chat_model or ""

    @property
    def metadata(self):
        return LLMMetadata(model_name=self._model, is_chat_model=True)

    def _payload(self, messages):
        return {
            "model": self._model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "temperature": 0,
        }

    def _headers(self):
        key = self._settings.llm_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    @staticmethod
    def _content(response):
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("LLM returned an invalid answer")
        return content

    async def achat(self, messages: Sequence[ChatMessage], **kwargs):
        seconds = remaining_timeout(kwargs.get("timeout", 60))
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(seconds, connect=min(10, seconds))
        ) as client:
            response = await client.post(
                f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
                json=self._payload(messages),
                headers=self._headers(),
            )
        return ChatResponse(message=ChatMessage(role="assistant", content=self._content(response)))

    def complete(self, prompt, formatted=False, **kwargs):
        with httpx.Client(timeout=kwargs.get("timeout", 60)) as client:
            response = client.post(
                f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
                json=self._payload([ChatMessage(role="user", content=prompt)]),
                headers=self._headers(),
            )
        return CompletionResponse(text=self._content(response))

    def stream_complete(self, prompt, formatted=False, **kwargs):
        raise NotImplementedError("Streaming is not supported")


async def completion(llm, messages, *, timeout=60):
    response = await llm.achat([ChatMessage(**message) for message in messages], timeout=timeout)
    return response.message.content
