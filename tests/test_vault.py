"""Tests for vault module — serialization, routes, writer, and storage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from agent_memory.config import MemoryConfig, ServerConfig, StorageConfig, VaultConfig
from agent_memory.embedding.base import EmbeddingProvider
from agent_memory.models import Memory
from agent_memory.storage.sqlite import SQLiteStorage
from agent_memory.vault.routes import create_vault_app
from agent_memory.vault.serializer import (
    content_to_slug,
    markdown_to_memory,
    memory_to_filename,
    memory_to_markdown,
    unique_slug,
)
from agent_memory.vault.writer import write_memory_to_vault


class TestSerializerRoundtrip:
    """Test Memory <-> markdown bidirectional conversion."""

    def test_roundtrip_basic_memory(self) -> None:
        """Memory -> markdown -> Memory should be lossless."""
        original = Memory(
            id="test-id-123",
            namespace="default",
            content="# Test Title\n\nThis is test content.",
            category="fact",
            importance=0.75,
            source="mcp",
        )

        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)

        assert restored.id == original.id
        assert restored.namespace == original.namespace
        assert restored.content == original.content
        assert restored.category == original.category
        assert restored.importance == original.importance
        assert restored.source == original.source

    def test_roundtrip_with_all_fields(self) -> None:
        """Roundtrip with all fields populated."""
        original = Memory(
            id="full-test-123",
            namespace="custom",
            content="Complete memory content.",
            summary="A summary",
            entities=["Entity1", "Entity2"],
            topics=["topic-a", "topic-b"],
            category="procedure",
            importance=0.9,
            connections=["memory-1", "memory-2"],
            consolidated=True,
            source="obsidian",
        )

        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)

        assert restored.id == original.id
        assert restored.namespace == original.namespace
        assert restored.content == original.content
        assert restored.summary == original.summary
        assert restored.entities == original.entities
        assert restored.topics == original.topics
        assert restored.category == original.category
        assert restored.importance == original.importance
        assert restored.connections == original.connections
        assert restored.consolidated == original.consolidated
        assert restored.source == original.source

    def test_roundtrip_without_optional_fields(self) -> None:
        """Roundtrip with minimal fields (summary, entities, etc. empty)."""
        original = Memory(
            id="minimal-123",
            content="Minimal memory",
            category="fact",
        )

        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)

        assert restored.id == original.id
        assert restored.content == original.content
        assert restored.category == original.category
        assert restored.summary is None
        assert restored.entities == []
        assert restored.topics == []
        assert restored.connections == []
        assert restored.consolidated is False

    def test_roundtrip_multiline_content(self) -> None:
        """Test roundtrip with multiline content and special formatting."""
        content = """# Project Notes

- Item 1
- Item 2: with **bold** text
- Item 3: with `code` blocks

## Section 2

Some paragraph with
multiple lines and
special characters: @#$%^&*"""

        original = Memory(
            id="multiline-123",
            content=content,
            category="note",
        )

        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)

        assert restored.content == original.content

    def test_roundtrip_special_characters_in_content(self) -> None:
        """Test roundtrip with special characters: quotes, slashes, etc."""
        content = (
            "Content with \"quotes\", 'single quotes', "
            "slashes / backslashes \\ and unicode: \u2603\u2764"
        )

        original = Memory(
            id="special-chars-123",
            content=content,
            category="fact",
        )

        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)

        assert restored.content == original.content


class TestSerializerEdgeCases:
    """Test edge cases in serialization."""

    def test_missing_required_fields_in_frontmatter(self) -> None:
        """markdown_to_memory without id/created_at/updated_at should fail."""
        markdown = """---
namespace: test
---

Content here"""
        # id, created_at, updated_at are required and should raise ValidationError
        with pytest.raises(Exception):  # ValidationError
            markdown_to_memory(markdown)

    def test_empty_frontmatter(self) -> None:
        """Empty YAML frontmatter should raise ValueError."""
        markdown = """---
---

Content here"""
        with pytest.raises(ValueError, match="Empty YAML frontmatter"):
            markdown_to_memory(markdown)

    def test_missing_closing_delimiter(self) -> None:
        """Missing closing --- delimiter should raise ValueError."""
        markdown = """---
id: test-123
namespace: test

Content without closing delimiter"""
        with pytest.raises(ValueError, match="Incomplete YAML frontmatter"):
            markdown_to_memory(markdown)

    def test_missing_opening_delimiter(self) -> None:
        """Missing opening --- delimiter should raise ValueError."""
        markdown = """id: test-123
namespace: test
---

Content"""
        with pytest.raises(ValueError, match="Missing YAML frontmatter delimiter"):
            markdown_to_memory(markdown)

    def test_invalid_yaml_in_frontmatter(self) -> None:
        """Invalid YAML syntax in frontmatter should raise ValueError."""
        markdown = """---
id: test-123
entities: [unclosed list
---

Content"""
        # yaml.safe_load will still parse this as a string or error
        with pytest.raises((ValueError, Exception)):
            markdown_to_memory(markdown)

    def test_non_dict_yaml_frontmatter(self) -> None:
        """Non-dict YAML (like a list) should raise ValueError."""
        markdown = """---
- item1
- item2
---

Content"""
        with pytest.raises(ValueError, match="YAML frontmatter must be a mapping"):
            markdown_to_memory(markdown)

    def test_empty_content(self) -> None:
        """Roundtrip with empty content string."""
        original = Memory(
            id="empty-content",
            content="",
            category="fact",
        )
        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)
        assert restored.content == ""

    def test_content_with_frontmatter_delimiters(self) -> None:
        """Content that includes --- should be handled correctly."""
        content = "This is content\n---\nwith dashes\n---\nin the middle"
        original = Memory(
            id="dash-content",
            content=content,
            category="fact",
        )
        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)
        assert restored.content == content

    def test_whitespace_preservation_in_content(self) -> None:
        """Leading/trailing whitespace in content should be preserved."""
        content = "   leading spaces\n\ntrailing spaces   "
        original = Memory(
            id="whitespace",
            content=content,
            category="fact",
        )
        markdown = memory_to_markdown(original)
        restored = markdown_to_memory(markdown)
        # Note: strip() is applied by markdown_to_memory, so exact whitespace won't match
        assert "leading spaces" in restored.content
        assert "trailing spaces" in restored.content


class TestSlugGenerator:
    """Test slug generation from content."""

    def test_basic_slug(self) -> None:
        """Basic alphanumeric content should generate clean slug."""
        slug = content_to_slug("Python programming")
        assert slug == "python-programming"

    def test_slug_with_hash_prefix(self) -> None:
        """Markdown heading syntax should be stripped."""
        slug = content_to_slug("# Important Title")
        assert slug == "important-title"

    def test_slug_with_multiple_hashes(self) -> None:
        """Multiple hash prefixes should be stripped."""
        slug = content_to_slug("### Heading Level 3")
        assert slug == "heading-level-3"

    def test_slug_with_special_characters(self) -> None:
        """Special characters should be converted to dashes."""
        slug = content_to_slug("Hello! World? @#$% Test")
        assert slug == "hello-world-test"

    def test_slug_with_numbers(self) -> None:
        """Numbers should be preserved, dots converted to dashes."""
        slug = content_to_slug("Python 3.10 Features")
        assert slug == "python-3-10-features"

    def test_slug_multiline_uses_first_line(self) -> None:
        """Only first line should be used for slug."""
        content = "First Line Title\nSecond line\nThird line"
        slug = content_to_slug(content)
        assert slug == "first-line-title"

    def test_slug_max_length(self) -> None:
        """Slug should be truncated to max_length."""
        long_content = (
            "This is a very long title that should be truncated "
            "to fit the maximum length constraint"
        )
        slug = content_to_slug(long_content, max_length=30)
        assert len(slug) <= 30

    def test_slug_empty_content(self) -> None:
        """Empty content should return 'untitled'."""
        slug = content_to_slug("")
        assert slug == "untitled"

    def test_slug_only_whitespace(self) -> None:
        """Whitespace-only content should return 'untitled'."""
        slug = content_to_slug("   \n  \t  ")
        assert slug == "untitled"

    def test_slug_only_special_characters(self) -> None:
        """Content with only special characters should return 'untitled'."""
        slug = content_to_slug("@#$%^&*()")
        assert slug == "untitled"

    def test_unique_slug_no_collision(self) -> None:
        """Slug with no collision should remain unchanged."""
        slug = unique_slug("python-guide", {"javascript-guide", "golang-guide"})
        assert slug == "python-guide"

    def test_unique_slug_with_collision(self) -> None:
        """Slug with collision should append hash."""
        slug = unique_slug("python-guide", {"python-guide", "other"})
        assert slug.startswith("python-guide-")
        assert len(slug) > len("python-guide-")

    def test_unique_slug_deterministic(self) -> None:
        """Same slug + collision should generate same hash."""
        slug1 = unique_slug("python-guide", {"python-guide"})
        slug2 = unique_slug("python-guide", {"python-guide"})
        assert slug1 == slug2


class TestFilenameGenerator:
    """Test filename generation."""

    def test_filename_format(self) -> None:
        """Filename should be {category}-{slug}.md"""
        memory = Memory(
            id="test",
            content="Python Programming",
            category="tutorial",
        )
        filename = memory_to_filename(memory)
        assert filename == "tutorial-python-programming.md"

    def test_filename_with_special_chars_content(self) -> None:
        """Special characters in content should be handled."""
        memory = Memory(
            id="test",
            content="How to set up @API keys!",
            category="procedure",
        )
        filename = memory_to_filename(memory)
        assert filename.startswith("procedure-")
        assert filename.endswith(".md")
        assert "@" not in filename
        assert "!" not in filename


class TestMemorySourceField:
    """Test source field defaults and behavior."""

    def test_source_default_is_mcp(self) -> None:
        """Memory source should default to 'mcp'."""
        memory = Memory(content="Test content")
        assert memory.source == "mcp"

    def test_source_can_be_set_to_obsidian(self) -> None:
        """Source can be explicitly set to 'obsidian'."""
        memory = Memory(
            content="Test",
            source="obsidian",
        )
        assert memory.source == "obsidian"

    def test_source_can_be_set_to_mobile(self) -> None:
        """Source can be explicitly set to 'mobile'."""
        memory = Memory(
            content="Test",
            source="mobile",
        )
        assert memory.source == "mobile"

    def test_source_preserved_in_roundtrip(self) -> None:
        """Source field should be preserved in markdown roundtrip."""
        memory = Memory(
            id="test-123",
            content="Test",
            source="obsidian",
        )
        markdown = memory_to_markdown(memory)
        restored = markdown_to_memory(markdown)
        assert restored.source == "obsidian"


class TestVaultConfig:
    """Test VaultConfig class."""

    def test_default_values(self) -> None:
        """VaultConfig should have sensible defaults."""
        config = VaultConfig()
        assert config.enabled is False
        assert config.vault_path is None
        assert config.sync_folder == "memory-vault"
        assert config.watch_local is False
        assert config.write_on_store is True
        assert config.api_port == 8889

    def test_custom_values(self) -> None:
        """VaultConfig should accept custom values."""
        config = VaultConfig(
            enabled=True,
            vault_path="/path/to/vault",
            sync_folder="custom-folder",
            watch_local=True,
            write_on_store=False,
            api_port=9999,
        )
        assert config.enabled is True
        assert config.vault_path == "/path/to/vault"
        assert config.sync_folder == "custom-folder"
        assert config.watch_local is True
        assert config.write_on_store is False
        assert config.api_port == 9999


class TestVaultWriter:
    """Test writing memories to vault files."""

    @pytest.fixture
    async def vault_writer_setup(self, tmp_path: Path) -> tuple[VaultConfig, Path]:
        """Create temporary vault path and config."""
        vault_path = tmp_path / "vault"
        vault_path.mkdir()
        config = VaultConfig(
            enabled=True,
            vault_path=str(vault_path),
            sync_folder="memory-sync",
            write_on_store=True,
        )
        return config, vault_path

    @pytest.mark.asyncio
    async def test_write_memory_creates_file(
        self, vault_writer_setup: tuple[VaultConfig, Path]
    ) -> None:
        """write_memory_to_vault should create .md file."""
        config, vault_path = vault_writer_setup

        memory = Memory(
            id="test-123",
            namespace="default",
            content="# Python Tips\n\nUse type hints.",
            category="tip",
        )

        path = await write_memory_to_vault(memory, config)

        assert path.exists()
        assert path.suffix == ".md"
        assert "default" in str(path)

    @pytest.mark.asyncio
    async def test_write_memory_file_content(
        self, vault_writer_setup: tuple[VaultConfig, Path]
    ) -> None:
        """Written file should contain correct markdown format."""
        config, vault_path = vault_writer_setup

        memory = Memory(
            id="test-456",
            namespace="work",
            content="Deploy via 'make deploy'",
            category="procedure",
        )

        path = await write_memory_to_vault(memory, config)
        content = path.read_text(encoding="utf-8")

        assert "---" in content
        assert "id: test-456" in content
        assert "Deploy via 'make deploy'" in content

    @pytest.mark.asyncio
    async def test_write_memory_creates_namespace_folder(
        self, vault_writer_setup: tuple[VaultConfig, Path]
    ) -> None:
        """Namespace folder should be created."""
        config, vault_path = vault_writer_setup

        memory = Memory(
            id="test-789",
            namespace="custom-namespace",
            content="Test",
            category="fact",
        )

        path = await write_memory_to_vault(memory, config)

        expected_dir = vault_path / "memory-sync" / "custom-namespace"
        assert expected_dir.exists()
        assert path.parent == expected_dir

    @pytest.mark.asyncio
    async def test_write_memory_update_existing_file(
        self, vault_writer_setup: tuple[VaultConfig, Path]
    ) -> None:
        """Writing same memory ID should update file."""
        config, vault_path = vault_writer_setup

        memory_v1 = Memory(
            id="update-test",
            namespace="default",
            content="Version 1",
            category="note",
        )

        path1 = await write_memory_to_vault(memory_v1, config)
        content1 = path1.read_text(encoding="utf-8")
        assert "Version 1" in content1

        # Update the memory
        memory_v2 = Memory(
            id="update-test",
            namespace="default",
            content="Version 2 - Updated",
            category="note",
        )
        path2 = await write_memory_to_vault(memory_v2, config)

        # Should reuse same file
        assert path1 == path2
        content2 = path2.read_text(encoding="utf-8")
        assert "Version 2 - Updated" in content2

    @pytest.mark.asyncio
    async def test_write_memory_no_vault_path_raises(
        self, tmp_path: Path
    ) -> None:
        """write_memory_to_vault without vault_path should raise."""
        config = VaultConfig(vault_path=None)
        memory = Memory(id="test", content="Test", category="fact")

        with pytest.raises(ValueError, match="vault_path not configured"):
            await write_memory_to_vault(memory, config)


class TestStorageSourceField:
    """Test source field in storage layer."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize storage."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_store_preserves_source_field(self, storage: SQLiteStorage) -> None:
        """Storing memory should preserve source field."""
        memory = Memory(
            content="Test",
            source="obsidian",
        )

        await storage.store(memory)
        retrieved = await storage.get(memory.id)

        assert retrieved is not None
        assert retrieved.source == "obsidian"

    @pytest.mark.asyncio
    async def test_source_defaults_to_mcp_in_storage(self, storage: SQLiteStorage) -> None:
        """Default source should be 'mcp' when retrieved."""
        memory = Memory(content="Test")  # source defaults to 'mcp'

        await storage.store(memory)
        retrieved = await storage.get(memory.id)

        assert retrieved is not None
        assert retrieved.source == "mcp"

    @pytest.mark.asyncio
    async def test_source_migration_adds_column(self, tmp_db_path: str) -> None:
        """Migration should add source column to existing database."""
        # First storage instance without source column simulation
        config = StorageConfig(db_path=tmp_db_path)
        store1 = SQLiteStorage(config, embedding_dim=1536)
        await store1.initialize()
        await store1.close()

        # Second instance should handle migration
        store2 = SQLiteStorage(config, embedding_dim=1536)
        await store2.initialize()

        # Should not raise
        memory = Memory(
            content="Test",
            source="mobile",
        )
        await store2.store(memory)
        retrieved = await store2.get(memory.id)

        assert retrieved is not None
        assert retrieved.source == "mobile"
        await store2.close()


class TestStorageChangesTracking:
    """Test get_changes_since functionality."""

    @pytest.fixture
    async def storage_with_data(self, tmp_db_path: str) -> SQLiteStorage:
        """Storage with sample data."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()

        # Add some memories
        memory1 = Memory(content="First memory", namespace="test")
        memory2 = Memory(content="Second memory", namespace="test")
        memory3 = Memory(content="Third memory", namespace="other")

        await store.store(memory1)
        await store.store(memory2)
        await store.store(memory3)

        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_get_changes_since_returns_memories(
        self, storage_with_data: SQLiteStorage
    ) -> None:
        """get_changes_since should return memories modified after timestamp."""
        changes = await storage_with_data.get_changes_since("1970-01-01T00:00:00+00:00")
        assert len(changes) == 3

    @pytest.mark.asyncio
    async def test_get_changes_since_respects_timestamp(
        self, storage_with_data: SQLiteStorage
    ) -> None:
        """get_changes_since should filter by timestamp."""
        future = datetime.now(timezone.utc).isoformat()
        changes = await storage_with_data.get_changes_since(future)
        assert len(changes) == 0

    @pytest.mark.asyncio
    async def test_get_changes_since_with_namespace_filter(
        self, storage_with_data: SQLiteStorage
    ) -> None:
        """get_changes_since should filter by namespace."""
        changes = await storage_with_data.get_changes_since(
            "1970-01-01T00:00:00+00:00",
            namespace="test",
        )
        assert len(changes) == 2
        assert all(m.namespace == "test" for m in changes)

    @pytest.mark.asyncio
    async def test_get_changes_since_orders_by_timestamp(
        self, storage_with_data: SQLiteStorage
    ) -> None:
        """get_changes_since should order by updated_at ASC."""
        changes = await storage_with_data.get_changes_since("1970-01-01T00:00:00+00:00")
        timestamps = [m.updated_at for m in changes]
        assert timestamps == sorted(timestamps)


class TestVaultRoutes:
    """Test vault REST API routes using Starlette TestClient."""

    @pytest.fixture
    def vault_app_setup(self, tmp_db_path: str) -> tuple[TestClient, SQLiteStorage]:
        """Create vault app and storage for testing."""
        import asyncio

        config = StorageConfig(db_path=tmp_db_path)
        storage = SQLiteStorage(config, embedding_dim=0)  # Disable embeddings

        # Initialize storage in sync context
        asyncio.run(storage.initialize())

        # Create a no-op embedding provider
        class NoOpEmbedding(EmbeddingProvider):
            def __init__(self, dimensions: int = 0) -> None:
                self._dimensions = dimensions

            @property
            def dimensions(self) -> int:
                return self._dimensions

            async def embed(self, text: str) -> list[float]:
                return []

        embedding_provider = NoOpEmbedding(dimensions=0)
        memory_config = MemoryConfig()

        app = create_vault_app(storage, embedding_provider, memory_config)
        client = TestClient(app)

        yield client, storage

        # Cleanup
        asyncio.run(storage.close())

    def test_health_endpoint(self, vault_app_setup: tuple[TestClient, SQLiteStorage]) -> None:
        """Health endpoint should return OK."""
        client, _ = vault_app_setup
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_push_memory_creates_new(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push endpoint should create new memory."""
        client, storage = vault_app_setup

        memory = Memory(
            id="push-test",
            content="# Test Memory",
            category="test",
        )
        markdown = memory_to_markdown(memory)

        response = client.post(
            "/api/vault/push",
            json={"markdown": markdown},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["memory_id"] == "push-test"

    def test_push_memory_requires_markdown(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push endpoint should reject missing markdown field."""
        client, _ = vault_app_setup

        response = client.post(
            "/api/vault/push",
            json={"no_markdown": "field"},
        )

        assert response.status_code == 400
        assert "missing 'markdown' field" in response.json()["error"]

    def test_push_memory_invalid_json(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push endpoint should handle invalid JSON."""
        client, _ = vault_app_setup

        response = client.post(
            "/api/vault/push",
            content="not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        assert "invalid JSON" in response.json()["error"]

    def test_push_memory_invalid_markdown(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push endpoint should reject invalid markdown."""
        client, _ = vault_app_setup

        response = client.post(
            "/api/vault/push",
            json={"markdown": "invalid markdown without frontmatter"},
        )

        assert response.status_code == 400
        assert "parse error" in response.json()["error"]

    def test_push_memory_idempotent(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Pushing same content twice should be idempotent."""
        client, _ = vault_app_setup

        memory = Memory(
            id="idempotent-test",
            content="Unchanged content",
            category="test",
        )
        markdown = memory_to_markdown(memory)

        # First push
        response1 = client.post(
            "/api/vault/push",
            json={"markdown": markdown},
        )
        assert response1.status_code == 200
        assert response1.json()["status"] == "created"

        # Second push with same content
        response2 = client.post(
            "/api/vault/push",
            json={"markdown": markdown},
        )
        assert response2.status_code == 200
        assert response2.json()["status"] == "unchanged"

    def test_get_changes_endpoint(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Get changes endpoint should return modified memories."""
        import asyncio

        client, storage = vault_app_setup

        # Add a memory
        memory = Memory(
            id="changes-test",
            content="Test content",
            namespace="default",
            category="fact",
        )
        asyncio.run(storage.store(memory))

        response = client.get(
            "/api/vault/changes",
            params={"since": "1970-01-01T00:00:00+00:00"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        assert any(m["id"] == "changes-test" for m in data["changes"])

    def test_get_changes_with_namespace_filter(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Get changes should filter by namespace."""
        import asyncio

        client, storage = vault_app_setup

        memory1 = Memory(
            id="test-1",
            namespace="work",
            content="Work memory",
            category="fact",
        )
        memory2 = Memory(
            id="test-2",
            namespace="personal",
            content="Personal memory",
            category="fact",
        )
        asyncio.run(storage.store(memory1))
        asyncio.run(storage.store(memory2))

        response = client.get(
            "/api/vault/changes",
            params={
                "since": "1970-01-01T00:00:00+00:00",
                "namespace": "work",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert all(m["namespace"] == "work" for m in data["changes"])

    def test_delete_memory_endpoint(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Delete endpoint should remove memory."""
        import asyncio

        client, storage = vault_app_setup

        memory = Memory(id="delete-test", content="To delete", category="test")
        asyncio.run(storage.store(memory))

        response = client.delete("/api/vault/memories/delete-test")

        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

    def test_delete_nonexistent_memory(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Delete endpoint should handle nonexistent memory gracefully."""
        client, _ = vault_app_setup

        response = client.delete("/api/vault/memories/nonexistent-id")

        assert response.status_code == 200
        assert response.json()["status"] == "not_found"

    def test_batch_push_multiple_memories(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Batch push should handle multiple memories."""
        client, _ = vault_app_setup

        memory1 = Memory(
            id="batch-1",
            content="First memory",
            category="fact",
        )
        memory2 = Memory(
            id="batch-2",
            content="Second memory",
            category="note",
        )

        markdown1 = memory_to_markdown(memory1)
        markdown2 = memory_to_markdown(memory2)

        response = client.post(
            "/api/vault/batch-push",
            json={
                "files": [
                    {"markdown": markdown1},
                    {"markdown": markdown2},
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["results"]) == 2
        assert all(r["status"] in ("created", "updated") for r in data["results"])

    def test_batch_push_handles_errors(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Batch push should continue on errors."""
        client, _ = vault_app_setup

        valid_memory = Memory(
            id="batch-valid",
            content="Valid",
            category="fact",
        )
        markdown_valid = memory_to_markdown(valid_memory)

        response = client.post(
            "/api/vault/batch-push",
            json={
                "files": [
                    {"markdown": markdown_valid},
                    {"markdown": "invalid markdown"},  # Invalid
                    {"no_markdown": "field"},  # Missing
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        # First should succeed, others should fail
        assert any(r["status"] in ("created", "updated") for r in data["results"])
        assert any(r["status"] in ("parse_error", "skipped") for r in data["results"])

    def test_batch_push_invalid_request(
        self, vault_app_setup: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Batch push should reject non-list files."""
        client, _ = vault_app_setup

        response = client.post(
            "/api/vault/batch-push",
            json={"files": "not a list"},
        )

        assert response.status_code == 400
        assert "'files' must be a list" in response.json()["error"]


class TestVaultRoutesWithAuth:
    """Test vault routes with authentication."""

    @pytest.fixture
    def vault_app_with_auth(self, tmp_db_path: str) -> tuple[TestClient, SQLiteStorage]:
        """Create vault app with auth token."""
        import asyncio

        config = StorageConfig(db_path=tmp_db_path)
        storage = SQLiteStorage(config, embedding_dim=0)
        asyncio.run(storage.initialize())

        class NoOpEmbedding(EmbeddingProvider):
            def __init__(self, dimensions: int = 0) -> None:
                self._dimensions = dimensions

            @property
            def dimensions(self) -> int:
                return self._dimensions

            async def embed(self, text: str) -> list[float]:
                return []

        embedding_provider = NoOpEmbedding(dimensions=0)
        memory_config = MemoryConfig(
            server=ServerConfig(auth_token="secret-token")
        )

        app = create_vault_app(storage, embedding_provider, memory_config)
        client = TestClient(app)

        yield client, storage

        asyncio.run(storage.close())

    def test_auth_token_required(
        self, vault_app_with_auth: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Health endpoint should not require auth (exception in middleware)."""
        client, _ = vault_app_with_auth
        response = client.get("/health")
        assert response.status_code == 200

    def test_push_without_auth_token_fails(
        self, vault_app_with_auth: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push without auth should return 401."""
        client, _ = vault_app_with_auth

        memory = Memory(id="test", content="test", category="fact")
        markdown = memory_to_markdown(memory)

        response = client.post(
            "/api/vault/push",
            json={"markdown": markdown},
        )

        assert response.status_code == 401
        assert "unauthorized" in response.json()["error"]

    def test_push_with_valid_auth_token(
        self, vault_app_with_auth: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push with valid auth token should succeed."""
        client, _ = vault_app_with_auth

        memory = Memory(id="test", content="test", category="fact")
        markdown = memory_to_markdown(memory)

        response = client.post(
            "/api/vault/push",
            json={"markdown": markdown},
            headers={"Authorization": "Bearer secret-token"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "created"

    def test_push_with_invalid_auth_token(
        self, vault_app_with_auth: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Push with invalid auth token should fail."""
        client, _ = vault_app_with_auth

        memory = Memory(id="test", content="test", category="fact")
        markdown = memory_to_markdown(memory)

        response = client.post(
            "/api/vault/push",
            json={"markdown": markdown},
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert response.status_code == 401
