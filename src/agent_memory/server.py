"""MCP server with memory tools, resources, and ingestion."""

from __future__ import annotations

import json
import logging
import signal
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from agent_memory.config import MemoryConfig
    from agent_memory.consolidation.engine import ConsolidationEngine
    from agent_memory.embedding.base import EmbeddingProvider
    from agent_memory.ingestion.processor import IngestionProcessor
    from agent_memory.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 10_000
MAX_RESULTS = 200


def create_mcp_server(
    storage: SQLiteStorage,
    embedding_provider: EmbeddingProvider,
    consolidation_engine: ConsolidationEngine | None,
    ingestion_processor: IngestionProcessor | None,
    config: MemoryConfig,
) -> FastMCP:
    """Create and configure the MCP server with all tools and resources."""

    mcp = FastMCP(
        "agent-memory",
        instructions=(
            "Memory system for AI agents. Store facts, search knowledge, "
            "track insights across sessions. Use namespaces to organize memories."
        ),
    )

    # ------------------------------------------------------------------
    # Shutdown manager [RT-14]
    # ------------------------------------------------------------------
    _shutdown_requested = False

    def _handle_signal(sig: int, _frame: object) -> None:
        nonlocal _shutdown_requested
        if _shutdown_requested:
            logger.warning("Force shutdown requested")
            raise SystemExit(1)
        _shutdown_requested = True
        logger.info("Graceful shutdown requested (signal %s)", sig)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def store_memory(
        content: str,
        namespace: str = "default",
        category: str = "fact",
        tags: list[str] | None = None,
        importance: float = 0.5,
    ) -> dict:
        """Store a new memory.

        Args:
            content: The memory content (max 10K chars).
            namespace: Namespace for organization (default: "default").
            category: One of: fact, preference, procedure, episode.
            tags: Optional topic tags.
            importance: 0.0-1.0 importance score.
        """
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH]

        from agent_memory.models import Memory

        memory = Memory(
            content=content,
            namespace=namespace,
            category=category,
            topics=tags or [],
            importance=max(0.0, min(1.0, importance)),
        )

        # Generate embedding if provider is configured
        embedding = None
        if embedding_provider.dimensions > 0:
            try:
                embedding = await embedding_provider.embed(content)
            except Exception as exc:
                logger.warning("Failed to generate embedding: %s", exc)

        memory_id = await storage.store(memory, embedding=embedding)

        return {
            "memory_id": memory_id,
            "namespace": namespace,
            "category": category,
            "status": "stored",
        }

    @mcp.tool()
    async def search_memory(
        query: str,
        namespace: str | None = None,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[dict]:
        """Search memories by semantic similarity.

        Args:
            query: Natural language search query.
            namespace: Filter by namespace (optional).
            top_k: Number of results to return (default: 10).
            category: Filter by category (optional).
        """
        top_k = min(top_k, MAX_RESULTS)
        embedding: list[float] = []
        if embedding_provider.dimensions > 0:
            try:
                embedding = await embedding_provider.embed(query)
            except Exception as exc:
                logger.warning("Failed to embed query: %s", exc)

        results = await storage.search(
            embedding=embedding,
            namespace=namespace,
            top_k=top_k,
            category=category,
        )

        return [
            {
                "id": r.memory.id,
                "content": r.memory.content,
                "summary": r.memory.summary,
                "similarity": round(r.similarity, 4),
                "category": r.memory.category,
                "namespace": r.memory.namespace,
                "importance": r.memory.importance,
                "created_at": r.memory.created_at,
            }
            for r in results
        ]

    @mcp.tool()
    async def update_memory(
        memory_id: str,
        content: str | None = None,
        importance: float | None = None,
        category: str | None = None,
    ) -> dict:
        """Update an existing memory.

        Args:
            memory_id: ID of the memory to update.
            content: New content (triggers re-embedding).
            importance: New importance score (0.0-1.0).
            category: New category.
        """
        fields: dict = {}
        if content is not None:
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH]
            fields["content"] = content
        if importance is not None:
            fields["importance"] = max(0.0, min(1.0, importance))
        if category is not None:
            fields["category"] = category

        # Re-embed if content changed
        if content is not None and embedding_provider.dimensions > 0:
            try:
                new_embedding = await embedding_provider.embed(content)
                fields["new_embedding"] = new_embedding
            except Exception as exc:
                logger.warning("Failed to re-embed: %s", exc)

        try:
            updated = await storage.update(memory_id, **fields)
        except ValueError as exc:
            return {"error": str(exc)}

        return {
            "memory_id": updated.id,
            "status": "updated",
            "content": updated.content[:200],
        }

    @mcp.tool()
    async def delete_memory(memory_id: str) -> dict:
        """Delete a memory by ID.

        Args:
            memory_id: ID of the memory to delete.
        """
        deleted = await storage.delete(memory_id)
        return {
            "memory_id": memory_id,
            "status": "deleted" if deleted else "not_found",
        }

    @mcp.tool()
    async def list_memories(
        namespace: str = "default",
        limit: int = 20,
        offset: int = 0,
        category: str | None = None,
    ) -> dict:
        """List memories in a namespace with pagination.

        Args:
            namespace: Namespace to list (default: "default").
            limit: Max results (default: 20).
            offset: Skip first N results.
            category: Filter by category (optional).
        """
        limit = min(limit, MAX_RESULTS)
        offset = max(offset, 0)
        memories = await storage.list(
            namespace=namespace,
            limit=limit,
            offset=offset,
            category=category,
        )

        stats = await storage.get_stats(namespace)

        return {
            "memories": [
                {
                    "id": m.id,
                    "content": m.content[:200],
                    "category": m.category,
                    "importance": m.importance,
                    "consolidated": m.consolidated,
                    "created_at": m.created_at,
                }
                for m in memories
            ],
            "total": stats["total_memories"],
            "namespace": namespace,
            "limit": limit,
            "offset": offset,
        }

    @mcp.tool()
    async def get_memory_stats(namespace: str | None = None) -> dict:
        """Get memory statistics.

        Args:
            namespace: Filter by namespace (optional — omit for global stats).
        """
        return await storage.get_stats(namespace)

    # ------------------------------------------------------------------
    # Consolidation tool (Phase 5 wires the engine)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def consolidate_memories(namespace: str = "default") -> dict:
        """Consolidate memories — find patterns, connections, and insights.

        Args:
            namespace: Namespace to consolidate (default: "default").
        """
        if consolidation_engine is None:
            return {"error": "Consolidation not configured. Set consolidation.provider in config."}

        try:
            result = await consolidation_engine.consolidate(namespace)
            return {
                "status": "completed",
                "summary": result.summary,
                "insight": result.insight,
                "source_count": len(result.source_ids),
                "namespace": namespace,
            }
        except Exception as exc:
            logger.error("Consolidation failed: %s", exc)
            return {"error": f"Consolidation failed: {exc}"}

    # ------------------------------------------------------------------
    # Ingestion tools (Phase 6)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def ingest_text(
        text: str,
        source: str = "manual",
        namespace: str = "default",
    ) -> dict:
        """Ingest raw text as a memory.

        Args:
            text: Text content to ingest.
            source: Label for the source (e.g. "notes", "chat-log").
            namespace: Target namespace.
        """
        if ingestion_processor is None:
            return {"error": "Ingestion not configured."}

        try:
            memory_id = await ingestion_processor.ingest_text(text, source, namespace)
            return {"memory_id": memory_id, "status": "ingested", "source": source}
        except Exception as exc:
            logger.error("Text ingestion failed: %s", exc)
            return {"error": f"Ingestion failed: {exc}"}

    @mcp.tool()
    async def ingest_file(
        file_path: str,
        namespace: str = "default",
    ) -> dict:
        """Ingest a text file as memories.

        Args:
            file_path: Path to the file (must be within allowed_paths).
            namespace: Target namespace.
        """
        if ingestion_processor is None:
            return {"error": "Ingestion not configured."}

        try:
            memory_id = await ingestion_processor.ingest_file(file_path, namespace)
            return {"memory_id": memory_id, "status": "ingested", "file": file_path}
        except Exception as exc:
            logger.error("File ingestion failed: %s", exc)
            return {"error": f"Ingestion failed: {exc}"}

    # ------------------------------------------------------------------
    # MCP Resources (Phase 7)
    # ------------------------------------------------------------------

    @mcp.resource("memory://stats")
    async def memory_stats_resource() -> str:
        """Current memory statistics across all namespaces."""
        stats = await storage.get_stats(None)
        return json.dumps(stats, indent=2)

    @mcp.resource("memory://recent/{namespace}")
    async def recent_memories_resource(namespace: str) -> str:
        """Last 10 memories in a namespace."""
        memories = await storage.list(namespace, limit=10, offset=0)
        return json.dumps(
            [m.model_dump() for m in memories],
            indent=2,
            default=str,
        )

    @mcp.resource("memory://namespaces")
    async def namespaces_resource() -> str:
        """List of all memory namespaces."""
        ns = await storage.list_namespaces()
        return json.dumps(
            [n.model_dump() for n in ns],
            indent=2,
            default=str,
        )

    @mcp.resource("memory://consolidations/{namespace}")
    async def consolidations_resource(namespace: str) -> str:
        """Recent consolidation insights for a namespace."""
        consolidations = await storage.get_consolidations(namespace, limit=10)
        return json.dumps(
            [c.model_dump() for c in consolidations],
            indent=2,
            default=str,
        )

    return mcp
