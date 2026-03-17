"""Shared test fixtures for agent memory tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_memory.config import EmbeddingConfig, IngestionConfig, StorageConfig
from agent_memory.models import Memory


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """Temporary SQLite database path."""
    return str(tmp_path / "test_memory.db")


@pytest.fixture
def storage_config(tmp_db_path: str) -> StorageConfig:
    """Storage config pointing to temp database."""
    return StorageConfig(db_path=tmp_db_path)


@pytest.fixture
def embedding_config() -> EmbeddingConfig:
    """Embedding config with no provider (noop)."""
    return EmbeddingConfig(provider=None)


@pytest.fixture
def ingestion_config(tmp_path: Path) -> IngestionConfig:
    """Ingestion config with tmp_path as allowed."""
    return IngestionConfig(allowed_paths=[str(tmp_path)])


@pytest.fixture
def sample_memory() -> Memory:
    """A sample memory for testing."""
    return Memory(
        content="Python was created by Guido van Rossum in 1991.",
        namespace="test",
        category="fact",
        importance=0.7,
        entities=["Python", "Guido van Rossum"],
        topics=["programming", "history"],
    )


@pytest.fixture
def sample_memories() -> list[Memory]:
    """Multiple sample memories for testing."""
    return [
        Memory(
            content="Python was created by Guido van Rossum in 1991.",
            namespace="test",
            category="fact",
            importance=0.7,
        ),
        Memory(
            content="The user prefers dark mode in their IDE.",
            namespace="test",
            category="preference",
            importance=0.5,
        ),
        Memory(
            content="To deploy, run 'make deploy' from the project root.",
            namespace="test",
            category="procedure",
            importance=0.8,
        ),
    ]
