"""LLM providers for consolidation — ABC, OpenAI-compatible, Ollama, and factory."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from agent_memory.config import ConsolidationConfig
from agent_memory.http_client import APIClient

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base for LLM text generation providers."""

    @abstractmethod
    async def generate(self, prompt: str, system: str = "") -> str:
        """Generate a text response given a user prompt and optional system message."""
        ...


class OpenAICompatibleLLM(LLMProvider):
    """OpenAI-compatible chat completions endpoint.

    Works with OpenAI, vLLM, LiteLLM, and Ollama /v1 compatibility layer.
    Uses the shared APIClient for retries and auth. [RT-15]
    """

    def __init__(self, api_client: APIClient, model: str) -> None:
        self._client = api_client
        self._model = model

    async def generate(self, prompt: str, system: str = "") -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.post(
            "/chat/completions",
            json={"model": self._model, "messages": messages},
        )
        return response["choices"][0]["message"]["content"]


class OllamaLLM(LLMProvider):
    """Ollama via /api/chat endpoint (native Ollama API, not OpenAI compat)."""

    def __init__(self, base_url: str, model: str) -> None:
        # Ollama runs locally — no auth needed
        self._client = APIClient(base_url=base_url, api_key=None)
        self._model = model

    async def generate(self, prompt: str, system: str = "") -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.post(
            "/api/chat",
            json={"model": self._model, "messages": messages, "stream": False},
        )
        return response["message"]["content"]


def create_llm_provider(config: ConsolidationConfig) -> LLMProvider:
    """Instantiate the correct LLM provider from consolidation config."""
    if config.provider == "ollama":
        return OllamaLLM(base_url=config.base_url, model=config.model)

    if config.provider in ("openai", "openai_compatible"):
        api_client = APIClient(
            base_url=config.base_url,
            api_key=config.api_key,
            allow_insecure=config.allow_insecure,
        )
        return OpenAICompatibleLLM(api_client=api_client, model=config.model)

    raise ValueError(f"Unknown consolidation provider: {config.provider!r}")
