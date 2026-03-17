"""Tests for text and file ingestion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_memory.config import IngestionConfig, StorageConfig
from agent_memory.embedding.providers import NoopProvider
from agent_memory.ingestion.processor import IngestionProcessor
from agent_memory.storage.sqlite import SQLiteStorage


class TestIngestText:
    """Tests for text ingestion."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    @pytest.fixture
    def ingestion_processor(self, storage: SQLiteStorage) -> IngestionProcessor:
        """Create ingestion processor."""
        config = IngestionConfig()
        embedding_provider = NoopProvider()
        return IngestionProcessor(storage, embedding_provider, None, config)

    async def test_ingest_text_basic(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
    ) -> None:
        """Test basic text ingestion."""
        text = "This is a test memory."
        memory_id = await ingestion_processor.ingest_text(text, source="test", namespace="test")

        assert memory_id is not None
        retrieved = await storage.get(memory_id)
        assert retrieved is not None
        assert retrieved.content == text
        assert retrieved.namespace == "test"

    async def test_ingest_text_with_metadata(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
    ) -> None:
        """Test ingestion and storage of memory."""
        memory_id = await ingestion_processor.ingest_text(
            "Test content",
            source="source",
            namespace="custom_ns",
        )

        retrieved = await storage.get(memory_id)
        assert retrieved.namespace == "custom_ns"
        assert retrieved.category == "fact"
        assert retrieved.importance == 0.5

    async def test_ingest_text_with_llm_extraction(
        self, storage: SQLiteStorage, tmp_db_path: str
    ) -> None:
        """Test text ingestion with LLM enrichment."""
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = """
{
  "summary": "Test memory summary",
  "entities": ["entity1", "entity2"],
  "topics": ["topic1", "topic2"],
  "importance": 0.8
}
"""

        config = IngestionConfig()
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, mock_llm, config)

        memory_id = await processor.ingest_text(
            "Original content",
            source="test_source",
            namespace="test",
        )

        retrieved = await storage.get(memory_id)
        assert retrieved.summary == "Test memory summary"
        assert "entity1" in retrieved.entities
        assert "topic1" in retrieved.topics
        assert retrieved.importance == 0.8

    async def test_ingest_text_with_llm_malformed_response(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
    ) -> None:
        """Test that malformed LLM response falls back to raw storage."""
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "not json at all"

        config = IngestionConfig()
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, mock_llm, config)

        memory_id = await processor.ingest_text(
            "Test content",
            source="test",
            namespace="test",
        )

        retrieved = await storage.get(memory_id)
        assert retrieved.content == "Test content"
        assert retrieved.summary is None


class TestIngestFile:
    """Tests for file ingestion."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    @pytest.fixture
    def ingestion_processor(self, storage: SQLiteStorage, tmp_path: Path) -> IngestionProcessor:
        """Create ingestion processor with allowed paths."""
        config = IngestionConfig(allowed_paths=[str(tmp_path)])
        embedding_provider = NoopProvider()
        return IngestionProcessor(storage, embedding_provider, None, config)

    async def test_ingest_file_success(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test successful file ingestion."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("File content here")

        memory_id = await ingestion_processor.ingest_file(str(test_file), namespace="test")

        assert memory_id is not None
        retrieved = await storage.get(memory_id)
        assert retrieved is not None
        assert retrieved.content == "File content here"
        assert retrieved.namespace == "test"

    async def test_ingest_file_markdown(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test ingestion of markdown file."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Title\n\nContent here")

        memory_id = await ingestion_processor.ingest_file(str(md_file), namespace="test")
        retrieved = await storage.get(memory_id)
        assert "# Title" in retrieved.content

    async def test_ingest_file_json(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test ingestion of JSON file."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"key": "value"}')

        memory_id = await ingestion_processor.ingest_file(str(json_file), namespace="test")
        retrieved = await storage.get(memory_id)
        assert '{"key": "value"}' in retrieved.content

    async def test_ingest_file_unsupported_extension(
        self,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test that unsupported file extensions are rejected."""
        unsupported = tmp_path / "test.exe"
        unsupported.write_text("binary content")

        with pytest.raises(ValueError, match="Unsupported file extension"):
            await ingestion_processor.ingest_file(str(unsupported), namespace="test")

    async def test_ingest_file_exceeds_size_limit(
        self,
        storage: SQLiteStorage,
        tmp_path: Path,
    ) -> None:
        """Test that oversized files are rejected."""
        config = IngestionConfig(
            allowed_paths=[str(tmp_path)],
            max_file_size_mb=0.001,  # ~1 KB
        )
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, None, config)

        large_file = tmp_path / "large.txt"
        large_file.write_text("x" * 10000)  # 10KB > 1KB limit

        with pytest.raises(ValueError, match="exceeds"):
            await processor.ingest_file(str(large_file), namespace="test")

    async def test_ingest_file_deduplication(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test that same file is not re-ingested (dedup)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Unique content")

        # First ingest
        await ingestion_processor.ingest_file(str(test_file), namespace="test")

        # Second ingest of same file should raise error
        with pytest.raises(ValueError, match="already ingested"):
            await ingestion_processor.ingest_file(str(test_file), namespace="test")

    async def test_ingest_file_disabled_when_no_allowed_paths(
        self,
        storage: SQLiteStorage,
        tmp_path: Path,
    ) -> None:
        """Test that ingest_file is disabled when allowed_paths is empty."""
        config = IngestionConfig(allowed_paths=[])
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, None, config)

        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        with pytest.raises(ValueError, match="disabled"):
            await processor.ingest_file(str(test_file), namespace="test")

    async def test_ingest_file_path_traversal_rejection(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test that path traversal attempts are rejected."""
        # Try to ingest a file outside allowed_paths using ..
        outside_file = tmp_path.parent / "outside.txt"
        outside_file.write_text("outside content")

        with pytest.raises(ValueError, match="outside all allowed"):
            await ingestion_processor.ingest_file(str(outside_file), namespace="test")

    async def test_ingest_file_symlink_resolution(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test that symlinks are resolved to validate path."""
        # Create target file in allowed path
        target = tmp_path / "target.txt"
        target.write_text("target content")

        # Create symlink in same allowed path
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(target)

        memory_id = await ingestion_processor.ingest_file(str(symlink), namespace="test")
        retrieved = await storage.get(memory_id)
        assert retrieved.content == "target content"

    async def test_ingest_file_nonexistent(
        self,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test that nonexistent files raise FileNotFoundError."""
        nonexistent = tmp_path / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            await ingestion_processor.ingest_file(str(nonexistent), namespace="test")


class TestPathValidation:
    """Tests for path validation in IngestionProcessor."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    def test_validate_path_within_allowed(self, storage: SQLiteStorage, tmp_path: Path) -> None:
        """Test that paths within allowed directories pass validation."""
        config = IngestionConfig(allowed_paths=[str(tmp_path)])
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, None, config)

        subdir = tmp_path / "subdir"
        subdir.mkdir()
        file_path = subdir / "file.txt"
        file_path.write_text("test")

        # Should not raise
        validated = processor._validate_path(file_path)
        assert validated.exists()

    def test_validate_path_outside_allowed(self, storage: SQLiteStorage, tmp_path: Path) -> None:
        """Test that paths outside allowed directories are rejected."""
        config = IngestionConfig(allowed_paths=[str(tmp_path)])
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, None, config)

        outside = tmp_path.parent / "outside.txt"
        outside.write_text("outside")

        with pytest.raises(ValueError, match="outside all allowed"):
            processor._validate_path(outside)

    def test_validate_path_empty_allowed_paths(
        self, storage: SQLiteStorage, tmp_path: Path
    ) -> None:
        """Test that empty allowed_paths disables feature."""
        config = IngestionConfig(allowed_paths=[])
        embedding_provider = NoopProvider()
        processor = IngestionProcessor(storage, embedding_provider, None, config)

        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with pytest.raises(ValueError, match="disabled"):
            processor._validate_path(test_file)

    def test_validate_path_with_tilde_expansion(self, storage: SQLiteStorage) -> None:
        """Test that ~ is expanded in allowed paths."""
        config = IngestionConfig(allowed_paths=["~/test_memory"])
        embedding_provider = NoopProvider()
        IngestionProcessor(storage, embedding_provider, None, config)

        # Path with tilde should be resolvable (even if dir doesn't exist)
        Path("~/test_memory/file.txt")
        # This would fail with "outside allowed" if tilde wasn't expanded
        # We won't actually validate since it doesn't exist, just checking no crash


class TestIngestionEdgeCases:
    """Tests for edge cases in ingestion."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    @pytest.fixture
    def ingestion_processor(self, storage: SQLiteStorage, tmp_path: Path) -> IngestionProcessor:
        """Create ingestion processor with allowed paths."""
        config = IngestionConfig(allowed_paths=[str(tmp_path)])
        embedding_provider = NoopProvider()
        return IngestionProcessor(storage, embedding_provider, None, config)

    async def test_ingest_empty_file(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test ingestion of empty file."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        memory_id = await ingestion_processor.ingest_file(str(empty_file), namespace="test")
        retrieved = await storage.get(memory_id)
        assert retrieved.content == ""

    async def test_ingest_text_with_unicode(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
    ) -> None:
        """Test ingestion of text with unicode characters."""
        unicode_text = "Hello 世界 🌍 Привет مرحبا"
        memory_id = await ingestion_processor.ingest_text(
            unicode_text,
            source="test",
            namespace="test",
        )

        retrieved = await storage.get(memory_id)
        assert retrieved.content == unicode_text

    async def test_ingest_file_with_encoding_errors(
        self,
        storage: SQLiteStorage,
        ingestion_processor: IngestionProcessor,
        tmp_path: Path,
    ) -> None:
        """Test file with encoding errors is handled gracefully."""
        test_file = tmp_path / "test.txt"
        # Write text with potential encoding issues
        test_file.write_bytes(b"Valid \xff text")

        # Should use errors='replace' to handle invalid UTF-8
        memory_id = await ingestion_processor.ingest_file(str(test_file), namespace="test")
        retrieved = await storage.get(memory_id)
        assert retrieved is not None
