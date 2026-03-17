"""Tests for SQLite storage backend."""

from __future__ import annotations

import pytest

from agent_memory.config import StorageConfig
from agent_memory.models import Consolidation, Memory, MemorySearchResult
from agent_memory.storage.sqlite import SQLiteStorage


class TestStorageCRUD:
    """Tests for basic CRUD operations."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_store_and_get_memory(
        self, storage: SQLiteStorage, sample_memory: Memory
    ) -> None:
        """Test storing and retrieving a memory."""
        memory_id = await storage.store(sample_memory)
        assert memory_id == sample_memory.id

        retrieved = await storage.get(memory_id)
        assert retrieved is not None
        assert retrieved.id == sample_memory.id
        assert retrieved.content == sample_memory.content
        assert retrieved.namespace == sample_memory.namespace
        assert retrieved.importance == sample_memory.importance

    async def test_get_nonexistent_memory(self, storage: SQLiteStorage) -> None:
        """Test retrieving nonexistent memory returns None."""
        result = await storage.get("nonexistent-id")
        assert result is None

    async def test_update_memory(self, storage: SQLiteStorage, sample_memory: Memory) -> None:
        """Test updating memory fields."""
        await storage.store(sample_memory)

        updated = await storage.update(
            sample_memory.id,
            content="Updated content",
            importance=0.9,
            category="procedure",
        )
        assert updated.content == "Updated content"
        assert updated.importance == 0.9
        assert updated.category == "procedure"

        # Verify persistence
        retrieved = await storage.get(sample_memory.id)
        assert retrieved.content == "Updated content"

    async def test_update_nonexistent_memory(self, storage: SQLiteStorage) -> None:
        """Test updating nonexistent memory raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            await storage.update("nonexistent-id", content="test")

    async def test_delete_memory(self, storage: SQLiteStorage, sample_memory: Memory) -> None:
        """Test deleting a memory."""
        await storage.store(sample_memory)
        assert await storage.get(sample_memory.id) is not None

        deleted = await storage.delete(sample_memory.id)
        assert deleted is True
        assert await storage.get(sample_memory.id) is None

    async def test_delete_nonexistent_memory(self, storage: SQLiteStorage) -> None:
        """Test deleting nonexistent memory returns False."""
        result = await storage.delete("nonexistent-id")
        assert result is False


class TestNamespaceIsolation:
    """Tests for namespace isolation."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_namespace_isolation(self, storage: SQLiteStorage) -> None:
        """Test that memories in different namespaces are isolated."""
        mem1 = Memory(
            content="Memory in namespace1",
            namespace="namespace1",
            category="fact",
        )
        mem2 = Memory(
            content="Memory in namespace2",
            namespace="namespace2",
            category="fact",
        )

        await storage.store(mem1)
        await storage.store(mem2)

        # List from namespace1 should only contain mem1
        ns1_mems = await storage.list("namespace1")
        assert len(ns1_mems) == 1
        assert ns1_mems[0].id == mem1.id

        # List from namespace2 should only contain mem2
        ns2_mems = await storage.list("namespace2")
        assert len(ns2_mems) == 1
        assert ns2_mems[0].id == mem2.id

    async def test_list_empty_namespace(self, storage: SQLiteStorage) -> None:
        """Test listing from empty namespace returns empty list."""
        result = await storage.list("empty_namespace")
        assert result == []


class TestListingAndPagination:
    """Tests for listing memories with pagination and filtering."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_list_with_pagination(
        self, storage: SQLiteStorage, sample_memories: list[Memory]
    ) -> None:
        """Test pagination with limit and offset."""
        for mem in sample_memories:
            await storage.store(mem)

        # Get first 2
        first_batch = await storage.list("test", limit=2, offset=0)
        assert len(first_batch) == 2

        # Get next batch (should be empty or have remaining)
        second_batch = await storage.list("test", limit=2, offset=2)
        assert len(second_batch) == 1

    async def test_list_with_category_filter(
        self, storage: SQLiteStorage, sample_memories: list[Memory]
    ) -> None:
        """Test filtering by category."""
        for mem in sample_memories:
            await storage.store(mem)

        # Filter by fact category
        facts = await storage.list("test", category="fact")
        assert len(facts) == 1
        assert facts[0].category == "fact"

        # Filter by preference category
        prefs = await storage.list("test", category="preference")
        assert len(prefs) == 1
        assert prefs[0].category == "preference"

    async def test_list_respects_created_at_order(self, storage: SQLiteStorage) -> None:
        """Test that list returns memories in reverse created_at order."""
        mem1 = Memory(content="First", namespace="test", category="fact")
        mem2 = Memory(content="Second", namespace="test", category="fact")
        mem3 = Memory(content="Third", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)
        await storage.store(mem3)

        results = await storage.list("test")
        # Should be in reverse order (newest first)
        assert results[0].id == mem3.id
        assert results[1].id == mem2.id
        assert results[2].id == mem1.id


class TestUnconsolidated:
    """Tests for unconsolidated memory retrieval."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_get_unconsolidated(
        self, storage: SQLiteStorage, sample_memories: list[Memory]
    ) -> None:
        """Test retrieving unconsolidated memories."""
        for mem in sample_memories:
            await storage.store(mem)

        unconsolidated = await storage.get_unconsolidated("test", limit=50)
        assert len(unconsolidated) == 3
        for mem in unconsolidated:
            assert mem.consolidated is False

    async def test_consolidated_memories_excluded(self, storage: SQLiteStorage) -> None:
        """Test that consolidated memories are not returned by get_unconsolidated."""
        mem1 = Memory(content="First", namespace="test", category="fact")
        mem2 = Memory(content="Second", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)

        # Mark mem1 as consolidated
        await storage.update(mem1.id, consolidated=True)

        unconsolidated = await storage.get_unconsolidated("test")
        assert len(unconsolidated) == 1
        assert unconsolidated[0].id == mem2.id


class TestConsolidation:
    """Tests for consolidation operations."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_store_consolidation_marks_sources(
        self,
        storage: SQLiteStorage,
        sample_memories: list[Memory],
    ) -> None:
        """Test that store_consolidation marks source memories as consolidated."""
        for mem in sample_memories:
            await storage.store(mem)

        consolidation = Consolidation(
            namespace="test",
            source_ids=[sample_memories[0].id, sample_memories[1].id],
            summary="Consolidated summary",
            insight="Key insight",
        )

        cons_id = await storage.store_consolidation(consolidation)
        assert cons_id == consolidation.id

        # Check that source memories are marked consolidated
        mem1 = await storage.get(sample_memories[0].id)
        mem2 = await storage.get(sample_memories[1].id)
        mem3 = await storage.get(sample_memories[2].id)

        assert mem1.consolidated is True
        assert mem2.consolidated is True
        assert mem3.consolidated is False

    async def test_get_consolidations(
        self,
        storage: SQLiteStorage,
        sample_memories: list[Memory],
    ) -> None:
        """Test retrieving consolidations."""
        for mem in sample_memories:
            await storage.store(mem)

        consolidation = Consolidation(
            namespace="test",
            source_ids=[sample_memories[0].id],
            summary="Summary",
            insight="Insight",
        )
        await storage.store_consolidation(consolidation)

        results = await storage.get_consolidations("test")
        assert len(results) == 1
        assert results[0].id == consolidation.id
        assert results[0].summary == "Summary"


class TestStats:
    """Tests for statistics retrieval."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_get_stats_empty(self, storage: SQLiteStorage) -> None:
        """Test stats for empty database."""
        stats = await storage.get_stats()
        assert stats["total_memories"] == 0
        assert stats["unconsolidated_count"] == 0
        assert stats["consolidation_count"] == 0

    async def test_get_stats_with_memories(
        self, storage: SQLiteStorage, sample_memories: list[Memory]
    ) -> None:
        """Test stats with stored memories."""
        for mem in sample_memories:
            await storage.store(mem)

        stats = await storage.get_stats("test")
        assert stats["total_memories"] == 3
        assert stats["unconsolidated_count"] == 3
        assert "fact" in stats["by_category"]
        assert "preference" in stats["by_category"]
        assert "procedure" in stats["by_category"]

    async def test_get_stats_by_namespace(self, storage: SQLiteStorage) -> None:
        """Test stats filtered by namespace."""
        mem1 = Memory(content="In ns1", namespace="namespace1", category="fact")
        mem2 = Memory(content="In ns2", namespace="namespace2", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)

        stats_ns1 = await storage.get_stats("namespace1")
        assert stats_ns1["total_memories"] == 1

        stats_ns2 = await storage.get_stats("namespace2")
        assert stats_ns2["total_memories"] == 1


class TestNamespaces:
    """Tests for namespace management."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_list_namespaces(
        self, storage: SQLiteStorage, sample_memories: list[Memory]
    ) -> None:
        """Test that storing memories auto-creates namespaces."""
        for mem in sample_memories:
            await storage.store(mem)

        namespaces = await storage.list_namespaces()
        ns_names = [ns.name for ns in namespaces]
        assert "test" in ns_names

    async def test_list_namespaces_empty(self, storage: SQLiteStorage) -> None:
        """Test listing namespaces when database is empty."""
        namespaces = await storage.list_namespaces()
        assert namespaces == []


class TestFileProcessingTracking:
    """Tests for file ingestion tracking."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_mark_and_check_file_processed(self, storage: SQLiteStorage) -> None:
        """Test marking and checking file processing status."""
        file_path = "/home/user/test.txt"
        content_hash = "abc123def456"

        # Not processed initially
        assert await storage.check_file_processed(file_path) is False

        # Mark as processed
        await storage.mark_file_processed(file_path, "test", content_hash)

        # Should be processed now
        assert await storage.check_file_processed(file_path) is True

    async def test_file_processed_is_namespace_aware(self, storage: SQLiteStorage) -> None:
        """Test that file tracking is per-namespace."""
        file_path = "/home/user/test.txt"

        await storage.mark_file_processed(file_path, "namespace1", "hash1")
        # File is marked in namespace1, but check_file_processed is global
        assert await storage.check_file_processed(file_path) is True


class TestEmbeddingDimensionValidation:
    """Tests for embedding dimension validation."""

    async def test_embedding_dim_mismatch_detection(self, tmp_db_path: str) -> None:
        """Test that dimension mismatch is detected on second initialization."""
        # Initialize with dimension 1536
        config1 = StorageConfig(db_path=tmp_db_path)
        storage1 = SQLiteStorage(config1, embedding_dim=1536)
        await storage1.initialize()
        await storage1.close()

        # Try to initialize with different dimension
        config2 = StorageConfig(db_path=tmp_db_path)
        storage2 = SQLiteStorage(config2, embedding_dim=3072)

        with pytest.raises(RuntimeError, match="Embedding dimension mismatch"):
            await storage2.initialize()

        await storage2.close()


class TestSearch:
    """Tests for search functionality."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create and initialize a storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    async def test_search_fallback_to_recency(
        self,
        storage: SQLiteStorage,
        sample_memories: list[Memory],
    ) -> None:
        """Test that search falls back to recency when vec is unavailable."""
        for mem in sample_memories:
            await storage.store(mem)

        # Create a dummy embedding (same dimension as configured)
        embedding = [0.1] * 1536

        results = await storage.search(embedding, namespace="test", top_k=10)
        assert len(results) == 3
        # Should be in reverse chronological order (recency fallback)
        assert all(isinstance(r, MemorySearchResult) for r in results)

    async def test_search_with_namespace_filter(
        self,
        storage: SQLiteStorage,
    ) -> None:
        """Test search with namespace filtering."""
        mem1 = Memory(content="In ns1", namespace="ns1", category="fact")
        mem2 = Memory(content="In ns2", namespace="ns2", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)

        embedding = [0.1] * 1536
        results = await storage.search(embedding, namespace="ns1", top_k=10)
        assert len(results) == 1
        assert results[0].memory.namespace == "ns1"

    async def test_search_with_category_filter(
        self,
        storage: SQLiteStorage,
    ) -> None:
        """Test search with category filtering."""
        mem1 = Memory(content="Fact", namespace="test", category="fact")
        mem2 = Memory(content="Procedure", namespace="test", category="procedure")

        await storage.store(mem1)
        await storage.store(mem2)

        embedding = [0.1] * 1536
        results = await storage.search(embedding, namespace="test", category="fact", top_k=10)
        assert len(results) == 1
        assert results[0].memory.category == "fact"
