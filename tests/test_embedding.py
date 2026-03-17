"""Tests for embedding providers."""

from __future__ import annotations

import pytest
import respx

from agent_memory.config import EmbeddingConfig
from agent_memory.embedding.providers import (
    NoopProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    create_provider,
)
from agent_memory.http_client import APIClient


class TestNoopProvider:
    """Tests for NoopProvider."""

    async def test_noop_provider_dimensions(self) -> None:
        """Test that NoopProvider returns 0 dimensions."""
        provider = NoopProvider()
        assert provider.dimensions == 0

    async def test_noop_provider_embed(self) -> None:
        """Test that NoopProvider returns empty embedding."""
        provider = NoopProvider()
        result = await provider.embed("test text")
        assert result == []

    async def test_noop_provider_embed_batch(self) -> None:
        """Test that NoopProvider batch embed returns empty lists."""
        provider = NoopProvider()
        results = await provider.embed_batch(["text1", "text2", "text3"])
        assert results == [[], [], []]


class TestCreateProvider:
    """Tests for provider factory function."""

    def test_create_provider_none(self) -> None:
        """Test creating provider with None returns NoopProvider."""
        config = EmbeddingConfig(provider=None)
        provider = create_provider(config)
        assert isinstance(provider, NoopProvider)
        assert provider.dimensions == 0

    def test_create_provider_none_string(self) -> None:
        """Test creating provider with 'none' returns NoopProvider."""
        config = EmbeddingConfig(provider="none")
        provider = create_provider(config)
        assert isinstance(provider, NoopProvider)

    def test_create_provider_openai(self) -> None:
        """Test creating OpenAI provider."""
        config = EmbeddingConfig(
            provider="openai",
            api_key="test-key",
            model="text-embedding-3-small",
            dimensions=1536,
        )
        provider = create_provider(config)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.dimensions == 1536

    def test_create_provider_ollama(self) -> None:
        """Test creating Ollama provider."""
        config = EmbeddingConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=768,
        )
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert provider.dimensions == 768

    def test_create_provider_unknown(self) -> None:
        """Test that unknown provider raises ValueError."""
        config = EmbeddingConfig(provider="unknown_provider")
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            create_provider(config)


class TestAPIClientHTTPSEnforcement:
    """Tests for HTTPS enforcement in APIClient."""

    def test_api_client_https_with_key(self) -> None:
        """Test that HTTPS is enforced when API key is provided."""
        # Should work with HTTPS
        client = APIClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        assert client is not None

    def test_api_client_http_with_key_raises(self) -> None:
        """Test that HTTP + API key raises ValueError."""
        with pytest.raises(ValueError, match="RT-15"):
            APIClient(
                base_url="http://api.openai.com/v1",
                api_key="test-key",
            )

    def test_api_client_http_with_key_allow_insecure(self) -> None:
        """Test that allow_insecure bypasses HTTPS enforcement."""
        client = APIClient(
            base_url="http://api.openai.com/v1",
            api_key="test-key",
            allow_insecure=True,
        )
        assert client is not None

    def test_api_client_http_without_key(self) -> None:
        """Test that HTTP is OK without API key."""
        client = APIClient(
            base_url="http://localhost:11434",
            api_key=None,
        )
        assert client is not None


class TestOpenAICompatibleProvider:
    """Tests for OpenAICompatibleProvider."""

    @respx.mock
    async def test_embed_success(self) -> None:
        """Test successful embedding generation."""
        mock_response = {
            "data": [
                {
                    "index": 0,
                    "embedding": [0.1, 0.2, 0.3] * 512,  # 1536 dimensions
                }
            ]
        }

        route = respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=respx.MockResponse(200, json=mock_response)
        )

        client = APIClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        provider = OpenAICompatibleProvider(client, "text-embedding-3-small", 1536)

        result = await provider.embed("test text")
        assert len(result) == 1536
        assert route.called

    @respx.mock
    async def test_embed_batch_success(self) -> None:
        """Test batch embedding generation."""
        mock_response = {
            "data": [
                {"index": 0, "embedding": [0.1] * 1536},
                {"index": 1, "embedding": [0.2] * 1536},
                {"index": 2, "embedding": [0.3] * 1536},
            ]
        }

        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=respx.MockResponse(200, json=mock_response)
        )

        client = APIClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        provider = OpenAICompatibleProvider(client, "text-embedding-3-small", 1536)

        results = await provider.embed_batch(["text1", "text2", "text3"])
        assert len(results) == 3
        assert all(len(r) == 1536 for r in results)

    @respx.mock
    async def test_embed_dimension_mismatch(self) -> None:
        """Test that dimension mismatch raises ValueError."""
        mock_response = {
            "data": [
                {
                    "index": 0,
                    "embedding": [0.1] * 768,  # Wrong dimension
                }
            ]
        }

        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=respx.MockResponse(200, json=mock_response)
        )

        client = APIClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        provider = OpenAICompatibleProvider(client, "text-embedding-3-small", 1536)

        with pytest.raises(ValueError, match="Expected 1536 dimensions"):
            await provider.embed("test text")

    @respx.mock
    async def test_embed_rate_limit_retry(self) -> None:
        """Test exponential backoff on 429 rate limit."""
        mock_response = {
            "data": [
                {
                    "index": 0,
                    "embedding": [0.1] * 1536,
                }
            ]
        }

        # First call returns 429, second returns success
        respx.post("https://api.openai.com/v1/embeddings").mock(
            side_effect=[
                respx.MockResponse(429),
                respx.MockResponse(200, json=mock_response),
            ]
        )

        client = APIClient(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        provider = OpenAICompatibleProvider(client, "text-embedding-3-small", 1536)

        result = await provider.embed("test text")
        assert len(result) == 1536


class TestOllamaProvider:
    """Tests for OllamaProvider."""

    @respx.mock
    async def test_embed_success(self) -> None:
        """Test successful embedding via Ollama."""
        mock_response = {
            "embeddings": [[0.1, 0.2, 0.3] * 256]  # 768 dimensions
        }

        respx.post("http://localhost:11434/api/embed").mock(
            return_value=respx.MockResponse(200, json=mock_response)
        )

        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=768,
        )

        result = await provider.embed("test text")
        assert len(result) == 768

    @respx.mock
    async def test_embed_single_embedding_format(self) -> None:
        """Test Ollama response with single embedding (not embeddings list)."""
        mock_response = {
            "embedding": [0.1, 0.2, 0.3] * 256  # 768 dimensions
        }

        respx.post("http://localhost:11434/api/embed").mock(
            return_value=respx.MockResponse(200, json=mock_response)
        )

        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=768,
        )

        result = await provider.embed("test text")
        assert len(result) == 768


class TestEmbeddingProviderABC:
    """Tests for EmbeddingProvider abstract base class."""

    async def test_embed_batch_default_implementation(self) -> None:
        """Test that embed_batch defaults to sequential embed calls."""
        provider = NoopProvider()
        results = await provider.embed_batch(["text1", "text2", "text3"])
        assert len(results) == 3
        assert all(r == [] for r in results)
