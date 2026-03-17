"""Embedding provider system."""

from agent_memory.embedding.base import EmbeddingProvider
from agent_memory.embedding.providers import (
    NoopProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    create_provider,
)

__all__ = [
    "EmbeddingProvider",
    "OpenAICompatibleProvider",
    "OllamaProvider",
    "NoopProvider",
    "create_provider",
]
