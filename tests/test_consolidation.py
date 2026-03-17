"""Tests for memory consolidation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from agent_memory.config import ConsolidationConfig, StorageConfig
from agent_memory.consolidation.engine import ConsolidationEngine, _parse_llm_json
from agent_memory.consolidation.prompts import (
    ConsolidationResponse,
    build_consolidation_prompt,
)
from agent_memory.models import Memory
from agent_memory.storage.sqlite import SQLiteStorage


class TestBuildConsolidationPrompt:
    """Tests for consolidation prompt building."""

    def test_build_prompt_single_memory(self) -> None:
        """Test building prompt with single memory."""
        memory = Memory(
            id="mem1",
            content="Python is great",
            namespace="test",
            category="fact",
        )
        prompt = build_consolidation_prompt([memory])
        assert "<memories>" in prompt
        assert "</memory>" in prompt
        assert "mem1" in prompt
        assert "Python is great" in prompt
        assert "<![CDATA[" in prompt

    def test_build_prompt_multiple_memories(self) -> None:
        """Test building prompt with multiple memories."""
        memories = [
            Memory(id="mem1", content="First fact", namespace="test", category="fact"),
            Memory(id="mem2", content="Second fact", namespace="test", category="fact"),
            Memory(id="mem3", content="Third fact", namespace="test", category="fact"),
        ]
        prompt = build_consolidation_prompt(memories)
        # Count opening <memory id= tags (not <memories> container)
        assert prompt.count("<memory id=") == 3
        assert prompt.count("</memory>") == 3
        assert "mem1" in prompt
        assert "mem2" in prompt
        assert "mem3" in prompt

    def test_build_prompt_cdata_escaping(self) -> None:
        """Test that ]]> in content is escaped with CDATA."""
        memory = Memory(
            id="mem1",
            content="Content with ]]> closing sequence",
            namespace="test",
            category="fact",
        )
        prompt = build_consolidation_prompt([memory])
        # Should be escaped as ]]]]><![CDATA[>
        assert "]]]]><![CDATA[>" in prompt
        # CDATA escaping: original ]]> becomes ]]]]><![CDATA[> which contains ]]> within CDATA
        # That's expected behavior for CDATA escaping

    def test_build_prompt_includes_tasks(self) -> None:
        """Test that prompt includes consolidation tasks."""
        memory = Memory(id="mem1", content="Test", namespace="test", category="fact")
        prompt = build_consolidation_prompt([memory])
        assert "Find connections" in prompt
        assert "summary" in prompt
        assert "insight" in prompt
        assert "duplicate" in prompt

    def test_build_prompt_json_structure(self) -> None:
        """Test that prompt requests specific JSON structure."""
        memory = Memory(id="mem1", content="Test", namespace="test", category="fact")
        prompt = build_consolidation_prompt([memory])
        assert '"summary"' in prompt
        assert '"insight"' in prompt
        assert '"connections"' in prompt
        assert '"duplicate_candidates"' in prompt


class TestConsolidationResponse:
    """Tests for ConsolidationResponse model."""

    def test_consolidation_response_basic(self) -> None:
        """Test creating ConsolidationResponse."""
        resp = ConsolidationResponse(
            summary="Consolidated summary",
            insight="Key insight",
        )
        assert resp.summary == "Consolidated summary"
        assert resp.insight == "Key insight"
        assert resp.connections == []
        assert resp.duplicate_candidates == []

    def test_consolidation_response_with_connections(self) -> None:
        """Test ConsolidationResponse with connections."""
        resp = ConsolidationResponse(
            summary="Summary",
            insight="Insight",
            connections=[
                {"from_id": "mem1", "to_id": "mem2", "relationship": "related_to"},
                {"from_id": "mem2", "to_id": "mem3", "relationship": "extends"},
            ],
        )
        assert len(resp.connections) == 2

    def test_consolidation_response_with_duplicates(self) -> None:
        """Test ConsolidationResponse with duplicate candidates."""
        resp = ConsolidationResponse(
            summary="Summary",
            insight="Insight",
            duplicate_candidates=["mem1", "mem2"],
        )
        assert len(resp.duplicate_candidates) == 2


class TestParseLLMJson:
    """Tests for JSON parsing with multiple fallback layers."""

    def test_parse_raw_json(self) -> None:
        """Test parsing raw JSON directly."""
        raw = '{"summary": "test", "insight": "insight"}'
        result = _parse_llm_json(raw)
        assert isinstance(result, ConsolidationResponse)
        assert result.summary == "test"
        assert result.insight == "insight"

    def test_parse_markdown_fence(self) -> None:
        """Test parsing JSON from markdown code fence."""
        raw = """Some text before
```json
{"summary": "test", "insight": "insight"}
```
Some text after"""
        result = _parse_llm_json(raw)
        assert isinstance(result, ConsolidationResponse)
        assert result.summary == "test"

    def test_parse_markdown_fence_no_language(self) -> None:
        """Test parsing from markdown fence without language specifier."""
        raw = """```
{"summary": "test", "insight": "insight"}
```"""
        result = _parse_llm_json(raw)
        assert isinstance(result, ConsolidationResponse)

    def test_parse_first_brace_block(self) -> None:
        """Test parsing first {...} block when JSON not in fence."""
        raw = """Some intro text
{"summary": "test", "insight": "insight"}
more text after"""
        result = _parse_llm_json(raw)
        assert isinstance(result, ConsolidationResponse)
        assert result.summary == "test"

    def test_parse_invalid_json_raises(self) -> None:
        """Test that invalid JSON at all layers raises ValueError."""
        raw = "Not JSON at all {and this is incomplete"
        with pytest.raises(ValueError, match="Failed to parse LLM response"):
            _parse_llm_json(raw)

    def test_parse_with_extra_fields(self) -> None:
        """Test parsing JSON with extra fields (should ignore them)."""
        raw = """{"summary": "test", "insight": "insight", "extra_field": "ignored"}"""
        result = _parse_llm_json(raw)
        assert result.summary == "test"
        assert result.insight == "insight"

    def test_parse_layers_in_order(self) -> None:
        """Test that parsing tries layers in correct order."""
        # Raw JSON without extra data is valid, should parse first
        raw = """{"summary": "from_raw", "insight": "raw_insight"}"""
        result = _parse_llm_json(raw)
        # Should use raw JSON
        assert result.summary == "from_raw"


class TestConsolidationEngine:
    """Tests for ConsolidationEngine."""

    @pytest.fixture
    async def storage(self, tmp_db_path: str) -> SQLiteStorage:
        """Create storage instance."""
        config = StorageConfig(db_path=tmp_db_path)
        store = SQLiteStorage(config, embedding_dim=1536)
        await store.initialize()
        yield store
        await store.close()

    @pytest.fixture
    def mock_llm_provider(self) -> AsyncMock:
        """Create mock LLM provider."""
        mock = AsyncMock()
        return mock

    @pytest.fixture
    def consolidation_config(self) -> ConsolidationConfig:
        """Create consolidation config."""
        return ConsolidationConfig(
            provider="openai",
            min_memories=3,
            auto_interval_minutes=0,
        )

    async def test_consolidate_success(
        self,
        storage: SQLiteStorage,
        mock_llm_provider: AsyncMock,
        consolidation_config: ConsolidationConfig,
    ) -> None:
        """Test successful consolidation."""
        # Store test memories
        mem1 = Memory(content="Fact 1", namespace="test", category="fact")
        mem2 = Memory(content="Fact 2", namespace="test", category="fact")
        mem3 = Memory(content="Fact 3", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)
        await storage.store(mem3)

        # Mock LLM response
        llm_response = json.dumps(
            {
                "summary": "Combined facts",
                "insight": "Key insight",
                "connections": [],
                "duplicate_candidates": [],
            }
        )
        mock_llm_provider.generate.return_value = llm_response

        engine = ConsolidationEngine(storage, mock_llm_provider, consolidation_config)
        consolidation = await engine.consolidate("test")

        assert consolidation.summary == "Combined facts"
        assert consolidation.insight == "Key insight"
        assert len(consolidation.source_ids) >= 3

        # Verify LLM was called
        assert mock_llm_provider.generate.called

    async def test_consolidate_min_memories_check(
        self,
        storage: SQLiteStorage,
        mock_llm_provider: AsyncMock,
        consolidation_config: ConsolidationConfig,
    ) -> None:
        """Test that consolidation requires minimum memories."""
        # Store only 2 memories
        mem1 = Memory(content="Fact 1", namespace="test", category="fact")
        mem2 = Memory(content="Fact 2", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)

        engine = ConsolidationEngine(storage, mock_llm_provider, consolidation_config)

        with pytest.raises(ValueError, match="Not enough unconsolidated memories"):
            await engine.consolidate("test")

    async def test_consolidate_locks_namespace(
        self,
        storage: SQLiteStorage,
        mock_llm_provider: AsyncMock,
        consolidation_config: ConsolidationConfig,
    ) -> None:
        """Test that consolidation is locked per-namespace."""
        # Store memories for two namespaces
        mem1 = Memory(content="Fact 1", namespace="ns1", category="fact")
        mem2 = Memory(content="Fact 2", namespace="ns1", category="fact")
        mem3 = Memory(content="Fact 3", namespace="ns1", category="fact")
        mem4 = Memory(content="Fact 4", namespace="ns2", category="fact")
        mem5 = Memory(content="Fact 5", namespace="ns2", category="fact")
        mem6 = Memory(content="Fact 6", namespace="ns2", category="fact")

        for mem in [mem1, mem2, mem3, mem4, mem5, mem6]:
            await storage.store(mem)

        llm_response = json.dumps(
            {
                "summary": "Summary",
                "insight": "Insight",
                "connections": [],
                "duplicate_candidates": [],
            }
        )
        mock_llm_provider.generate.return_value = llm_response

        engine = ConsolidationEngine(storage, mock_llm_provider, consolidation_config)

        # Get locks for each namespace
        lock1 = engine._get_lock("ns1")
        lock2 = engine._get_lock("ns2")

        # Same namespace should get same lock
        lock1_again = engine._get_lock("ns1")
        assert lock1 is lock1_again

        # Different namespaces get different locks
        assert lock1 is not lock2

    async def test_consolidate_marks_sources_consolidated(
        self,
        storage: SQLiteStorage,
        mock_llm_provider: AsyncMock,
        consolidation_config: ConsolidationConfig,
    ) -> None:
        """Test that consolidation marks source memories as consolidated."""
        mem1 = Memory(content="Fact 1", namespace="test", category="fact")
        mem2 = Memory(content="Fact 2", namespace="test", category="fact")
        mem3 = Memory(content="Fact 3", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)
        await storage.store(mem3)

        llm_response = json.dumps(
            {
                "summary": "Summary",
                "insight": "Insight",
                "connections": [],
                "duplicate_candidates": [],
            }
        )
        mock_llm_provider.generate.return_value = llm_response

        engine = ConsolidationEngine(storage, mock_llm_provider, consolidation_config)
        await engine.consolidate("test")

        # Check that memories are marked consolidated
        m1 = await storage.get(mem1.id)
        m2 = await storage.get(mem2.id)
        m3 = await storage.get(mem3.id)

        assert m1.consolidated is True
        assert m2.consolidated is True
        assert m3.consolidated is True

    async def test_consolidate_retry_on_parse_failure(
        self,
        storage: SQLiteStorage,
        mock_llm_provider: AsyncMock,
        consolidation_config: ConsolidationConfig,
    ) -> None:
        """Test that consolidation retries on parse failure."""
        mem1 = Memory(content="Fact 1", namespace="test", category="fact")
        mem2 = Memory(content="Fact 2", namespace="test", category="fact")
        mem3 = Memory(content="Fact 3", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)
        await storage.store(mem3)

        # First call returns invalid JSON, second returns valid
        valid_response = json.dumps(
            {
                "summary": "Summary",
                "insight": "Insight",
                "connections": [],
                "duplicate_candidates": [],
            }
        )
        mock_llm_provider.generate.side_effect = [
            "Invalid JSON {",
            valid_response,
        ]

        engine = ConsolidationEngine(storage, mock_llm_provider, consolidation_config)
        consolidation = await engine.consolidate("test")

        assert consolidation.summary == "Summary"
        # Should have been called twice (once for failure, once for success)
        assert mock_llm_provider.generate.call_count == 2

    async def test_consolidate_with_duplicate_candidates(
        self,
        storage: SQLiteStorage,
        mock_llm_provider: AsyncMock,
        consolidation_config: ConsolidationConfig,
    ) -> None:
        """Test consolidation with flagged duplicate candidates."""
        mem1 = Memory(content="Fact 1", namespace="test", category="fact")
        mem2 = Memory(content="Fact 1 (duplicate)", namespace="test", category="fact")
        mem3 = Memory(content="Fact 3", namespace="test", category="fact")

        await storage.store(mem1)
        await storage.store(mem2)
        await storage.store(mem3)

        llm_response = json.dumps(
            {
                "summary": "Summary",
                "insight": "Insight",
                "connections": [],
                "duplicate_candidates": [mem2.id],  # Flag mem2 as duplicate
            }
        )
        mock_llm_provider.generate.return_value = llm_response

        engine = ConsolidationEngine(storage, mock_llm_provider, consolidation_config)
        await engine.consolidate("test")

        # Duplicate should be flagged, but memory should still exist
        m2 = await storage.get(mem2.id)
        assert m2 is not None
        assert m2.consolidated is True
