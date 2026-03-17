"""Concrete embedding providers and factory function."""

from __future__ import annotations

import logging

from agent_memory.config import EmbeddingConfig
from agent_memory.embedding.base import EmbeddingProvider
from agent_memory.http_client import APIClient

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(EmbeddingProvider):
    """Embedding provider for OpenAI-compatible endpoints.

    Works with OpenAI, Together, Fireworks, vLLM, LiteLLM, and others.
    """

    def __init__(self, api_client: APIClient, model: str, dimensions: int) -> None:
        self._client = api_client
        self._model = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        response = await self._client.post(
            "/embeddings",
            json={"model": self._model, "input": text},
        )
        vector: list[float] = response["data"][0]["embedding"]
        self._validate_dimensions(vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed via single API call."""
        response = await self._client.post(
            "/embeddings",
            json={"model": self._model, "input": texts},
        )
        # Sort by index to preserve order
        items = sorted(response["data"], key=lambda x: x["index"])
        vectors = [item["embedding"] for item in items]
        for v in vectors:
            self._validate_dimensions(v)
        return vectors

    def _validate_dimensions(self, vector: list[float]) -> None:
        if len(vector) != self._dimensions:
            raise ValueError(
                f"Expected {self._dimensions} dimensions, got {len(vector)}"
            )


class OllamaProvider(EmbeddingProvider):
    """Embedding provider for Ollama."""

    def __init__(self, base_url: str, model: str, dimensions: int) -> None:
        # Ollama needs no auth; create its own APIClient
        self._client = APIClient(base_url=base_url, api_key=None)
        self._model = model
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        response = await self._client.post(
            "/api/embed",
            json={"model": self._model, "input": text},
        )
        # Ollama returns {"embeddings": [[...]]} for input list, or {"embedding": [...]}
        if "embeddings" in response:
            vector: list[float] = response["embeddings"][0]
        else:
            vector = response["embedding"]
        return vector


class NoopProvider(EmbeddingProvider):
    """No-op provider — signals storage to skip vector operations."""

    @property
    def dimensions(self) -> int:
        return 0

    async def embed(self, text: str) -> list[float]:
        return []


def create_provider(config: EmbeddingConfig) -> EmbeddingProvider:
    """Instantiate the correct provider from config."""
    if config.provider is None or config.provider == "none":
        return NoopProvider()

    if config.provider == "openai":
        api_client = APIClient(
            base_url=config.base_url,
            api_key=config.api_key,
            allow_insecure=config.allow_insecure,
        )
        return OpenAICompatibleProvider(api_client, config.model, config.dimensions)

    if config.provider == "ollama":
        return OllamaProvider(config.base_url, config.model, config.dimensions)

    raise ValueError(f"Unknown embedding provider: {config.provider!r}")
