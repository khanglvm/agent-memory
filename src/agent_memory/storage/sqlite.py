"""SQLite storage backend for agent memory."""

from __future__ import annotations

import json
import logging
import struct
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from agent_memory.config import StorageConfig
from agent_memory.models import Consolidation, Memory, MemorySearchResult, Namespace

logger = logging.getLogger(__name__)

_VEC_AVAILABLE = True
try:
    import sqlite_vec
except ImportError:
    _VEC_AVAILABLE = False
    logger.warning("sqlite-vec not available — vector search disabled")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_memory(row: aiosqlite.Row) -> Memory:
    """Convert a DB row to a Memory model."""
    return Memory(
        id=row["id"],
        namespace=row["namespace"],
        content=row["content"],
        summary=row["summary"],
        entities=json.loads(row["entities"] or "[]"),
        topics=json.loads(row["topics"] or "[]"),
        category=row["category"],
        importance=row["importance"],
        connections=json.loads(row["connections"] or "[]"),
        consolidated=bool(row["consolidated"]),
        source=row["source"] if "source" in row.keys() else "mcp",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_consolidation(row: aiosqlite.Row) -> Consolidation:
    return Consolidation(
        id=row["id"],
        namespace=row["namespace"],
        source_ids=json.loads(row["source_ids"] or "[]"),
        summary=row["summary"],
        insight=row["insight"],
        created_at=row["created_at"],
    )


def _pack_embedding(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


class SQLiteStorage:
    """Async SQLite storage with optional sqlite-vec vector search."""

    def __init__(self, config: StorageConfig, embedding_dim: int = 1536) -> None:
        self._config = config
        self._embedding_dim = embedding_dim
        self._db: aiosqlite.Connection | None = None
        self._vec_enabled = _VEC_AVAILABLE

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open DB, create schema, validate embedding dim."""
        db_path = self._config.resolved_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # isolation_level=None → autocommit / manual transaction control
        self._db = await aiosqlite.connect(str(db_path), isolation_level=None)
        self._db.row_factory = aiosqlite.Row

        await self._db.execute("PRAGMA journal_mode=WAL")

        if self._vec_enabled:
            try:
                await self._db.enable_load_extension(True)
                await self._db.load_extension(sqlite_vec.loadable_path())
                await self._db.enable_load_extension(False)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to load sqlite-vec extension: %s — vector search disabled", exc
                )
                self._vec_enabled = False

        await self._create_schema()
        await self._migrate_add_source_column()
        await self._validate_embedding_dim()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def _create_schema(self) -> None:
        assert self._db is not None
        dim = self._embedding_dim

        # executescript commits any pending transaction and runs statements
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                summary TEXT,
                entities TEXT DEFAULT '[]',
                topics TEXT DEFAULT '[]',
                category TEXT DEFAULT 'fact',
                importance REAL DEFAULT 0.5,
                connections TEXT DEFAULT '[]',
                consolidated INTEGER DEFAULT 0,
                source TEXT DEFAULT 'mcp',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);
            CREATE INDEX IF NOT EXISTS idx_memories_consolidated ON memories(consolidated);
            CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at);

            CREATE TABLE IF NOT EXISTS consolidations (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL DEFAULT 'default',
                source_ids TEXT NOT NULL,
                summary TEXT NOT NULL,
                insight TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS namespaces (
                name TEXT PRIMARY KEY,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS processed_files (
                path TEXT PRIMARY KEY,
                namespace TEXT NOT NULL DEFAULT 'default',
                hash TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );
        """)

        if self._vec_enabled:
            try:
                await self._db.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
                        id TEXT PRIMARY KEY,
                        embedding float[{dim}]
                    )
                """)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to create vec0 virtual table: %s — vector search disabled", exc
                )
                self._vec_enabled = False

    async def _validate_embedding_dim(self) -> None:
        assert self._db is not None
        stored = await self._get_metadata("embedding_dim")
        if stored is None:
            await self._set_metadata("embedding_dim", str(self._embedding_dim))
        else:
            stored_dim = int(stored)
            if stored_dim != self._embedding_dim:
                raise RuntimeError(
                    f"Embedding dimension mismatch: database has {stored_dim}, "
                    f"but config specifies {self._embedding_dim}. "
                    "Either use the same dimension or delete the database and start fresh."
                )

    async def _get_metadata(self, key: str) -> str | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def _set_metadata(self, key: str, value: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )

    async def _migrate_add_source_column(self) -> None:
        """Add source column to memories table if missing (migration)."""
        assert self._db is not None
        async with self._db.execute("PRAGMA table_info(memories)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "source" not in columns:
            await self._db.execute(
                "ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'mcp'"
            )

    # ------------------------------------------------------------------
    # Change tracking
    # ------------------------------------------------------------------

    async def get_changes_since(
        self, since: str, namespace: str | None = None
    ) -> list[Memory]:
        """Return memories with updated_at > since."""
        assert self._db is not None
        query = "SELECT * FROM memories WHERE updated_at > ?"
        params: list[Any] = [since]
        if namespace:
            query += " AND namespace = ?"
            params.append(namespace)
        query += " ORDER BY updated_at ASC"
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_memory(r) for r in rows]

    # ------------------------------------------------------------------
    # Namespace helpers
    # ------------------------------------------------------------------

    async def _ensure_namespace(self, namespace: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR IGNORE INTO namespaces (name, description, created_at)"
            " VALUES (?, ?, ?)",
            (namespace, "", _utc_now()),
        )

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    async def store(self, memory: Memory, embedding: list[float] | None = None) -> str:
        """Persist memory + optional embedding in a single transaction."""
        assert self._db is not None

        await self._db.execute("BEGIN")
        try:
            await self._ensure_namespace(memory.namespace)
            await self._db.execute(
                """
                INSERT OR REPLACE INTO memories
                    (id, namespace, content, summary, entities, topics, category,
                     importance, connections, consolidated, source,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.namespace,
                    memory.content,
                    memory.summary,
                    json.dumps(memory.entities),
                    json.dumps(memory.topics),
                    memory.category,
                    memory.importance,
                    json.dumps(memory.connections),
                    int(memory.consolidated),
                    memory.source,
                    memory.created_at,
                    memory.updated_at,
                ),
            )

            if embedding is not None and self._vec_enabled:
                blob = _pack_embedding(embedding)
                await self._db.execute(
                    "INSERT OR REPLACE INTO memory_vectors (id, embedding) VALUES (?, ?)",
                    (memory.id, blob),
                )

            await self._db.execute("COMMIT")
        except Exception:
            await self._db.execute("ROLLBACK")
            raise

        return memory.id

    async def get(self, memory_id: str) -> Memory | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_memory(row) if row else None

    _ALLOWED_UPDATE_FIELDS = frozenset({
        "content", "summary", "entities", "topics", "category",
        "importance", "connections", "consolidated", "source", "updated_at",
    })

    async def update(self, memory_id: str, **fields: Any) -> Memory:
        """Update specified fields. Pass new_embedding kwarg if content changed."""
        assert self._db is not None
        memory = await self.get(memory_id)
        if memory is None:
            raise ValueError(f"Memory {memory_id!r} not found")

        new_embedding: list[float] | None = fields.pop("new_embedding", None)
        fields["updated_at"] = _utc_now()

        # [H-2] Allowlist column names to prevent SQL injection via kwargs
        invalid = set(fields) - self._ALLOWED_UPDATE_FIELDS
        if invalid:
            raise ValueError(f"Invalid update fields: {invalid}")

        # Serialize list fields
        for list_field in ("entities", "topics", "connections"):
            if list_field in fields and isinstance(fields[list_field], list):
                fields[list_field] = json.dumps(fields[list_field])

        if "consolidated" in fields:
            fields["consolidated"] = int(fields["consolidated"])

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [memory_id]

        await self._db.execute(
            f"UPDATE memories SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )

        if new_embedding is not None and self._vec_enabled:
            blob = _pack_embedding(new_embedding)
            await self._db.execute(
                "INSERT OR REPLACE INTO memory_vectors (id, embedding) VALUES (?, ?)",
                (memory_id, blob),
            )

        updated = await self.get(memory_id)
        assert updated is not None
        return updated

    async def delete(self, memory_id: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM memories WHERE id = ?", (memory_id,)
        )
        if self._vec_enabled:
            await self._db.execute(
                "DELETE FROM memory_vectors WHERE id = ?", (memory_id,)
            )
        return cursor.rowcount > 0

    async def list(
        self,
        namespace: str,
        limit: int = 20,
        offset: int = 0,
        category: str | None = None,
    ) -> list[Memory]:
        assert self._db is not None
        if category:
            sql = (
                "SELECT * FROM memories WHERE namespace = ? AND category = ?"
                " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            )
            params: tuple = (namespace, category, limit, offset)
        else:
            sql = (
                "SELECT * FROM memories WHERE namespace = ?"
                " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            )
            params = (namespace, limit, offset)

        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_memory(r) for r in rows]

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------

    async def search(
        self,
        embedding: list[float],
        namespace: str | None = None,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[MemorySearchResult]:
        assert self._db is not None

        if self._vec_enabled:
            return await self._vector_search(embedding, namespace, top_k, category)

        return await self._recency_fallback(namespace, top_k, category)

    async def _vector_search(
        self,
        embedding: list[float],
        namespace: str | None,
        top_k: int,
        category: str | None,
    ) -> list[MemorySearchResult]:
        assert self._db is not None

        # Check if any vectors exist
        async with self._db.execute(
            "SELECT COUNT(*) as cnt FROM memory_vectors"
        ) as cursor:
            row = await cursor.fetchone()
            if row["cnt"] == 0:
                return await self._recency_fallback(namespace, top_k, category)

        blob = _pack_embedding(embedding)

        # vec0 KNN query — namespace/category filters applied post-join
        sql = """
            SELECT v.id, v.distance
            FROM memory_vectors v
            JOIN memories m ON m.id = v.id
            WHERE v.embedding MATCH ?
              AND k = ?
        """
        params: list[Any] = [blob, top_k]

        if namespace:
            sql += " AND m.namespace = ?"
            params.append(namespace)
        if category:
            sql += " AND m.category = ?"
            params.append(category)

        try:
            async with self._db.execute(sql, params) as cursor:
                vec_rows = await cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector search failed: %s — falling back to recency", exc)
            return await self._recency_fallback(namespace, top_k, category)

        if not vec_rows:
            return await self._recency_fallback(namespace, top_k, category)

        results: list[MemorySearchResult] = []
        for vr in vec_rows:
            mem = await self.get(vr["id"])
            if mem is None:
                continue
            distance = float(vr["distance"])
            similarity = 1.0 / (1.0 + distance)
            results.append(MemorySearchResult(memory=mem, similarity=similarity))

        return results

    async def _recency_fallback(
        self,
        namespace: str | None,
        top_k: int,
        category: str | None,
    ) -> list[MemorySearchResult]:
        assert self._db is not None
        conditions: list[str] = []
        params: list[Any] = []

        if namespace:
            conditions.append("namespace = ?")
            params.append(namespace)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(top_k)

        sql = (
            f"SELECT * FROM memories {where} ORDER BY created_at DESC LIMIT ?"  # noqa: S608
        )
        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [MemorySearchResult(memory=_row_to_memory(r), similarity=0.0) for r in rows]

    # ------------------------------------------------------------------
    # Unconsolidated
    # ------------------------------------------------------------------

    async def get_unconsolidated(self, namespace: str, limit: int = 50) -> list[Memory]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM memories WHERE namespace = ? AND consolidated = 0"
            " ORDER BY created_at ASC LIMIT ?",
            (namespace, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_memory(r) for r in rows]

    # ------------------------------------------------------------------
    # Consolidations
    # ------------------------------------------------------------------

    async def store_consolidation(self, consolidation: Consolidation) -> str:
        """Persist consolidation + mark source memories consolidated atomically."""
        assert self._db is not None

        await self._db.execute("BEGIN")
        try:
            await self._db.execute(
                """
                INSERT OR REPLACE INTO consolidations
                    (id, namespace, source_ids, summary, insight, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    consolidation.id,
                    consolidation.namespace,
                    json.dumps(consolidation.source_ids),
                    consolidation.summary,
                    consolidation.insight,
                    consolidation.created_at,
                ),
            )

            if consolidation.source_ids:
                placeholders = ",".join("?" * len(consolidation.source_ids))
                await self._db.execute(
                    f"UPDATE memories SET consolidated = 1"  # noqa: S608
                    f" WHERE id IN ({placeholders})",
                    consolidation.source_ids,
                )

            await self._db.execute("COMMIT")
        except Exception:
            await self._db.execute("ROLLBACK")
            raise

        return consolidation.id

    async def mark_consolidated(self, memory_ids: list[str]) -> None:
        assert self._db is not None
        if not memory_ids:
            return
        placeholders = ",".join("?" * len(memory_ids))
        await self._db.execute(
            f"UPDATE memories SET consolidated = 1 WHERE id IN ({placeholders})",  # noqa: S608
            memory_ids,
        )

    async def get_consolidations(
        self, namespace: str, limit: int = 20
    ) -> list[Consolidation]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM consolidations WHERE namespace = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (namespace, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_consolidation(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self, namespace: str | None = None) -> dict:
        assert self._db is not None
        conditions: list[str] = []
        params: list[Any] = []

        if namespace:
            conditions.append("namespace = ?")
            params.append(namespace)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with self._db.execute(
            f"SELECT COUNT(*) as cnt FROM memories {where}", params  # noqa: S608
        ) as cursor:
            row = await cursor.fetchone()
            total_memories = row["cnt"]

        async with self._db.execute(
            f"SELECT category, COUNT(*) as cnt FROM memories {where}"  # noqa: S608
            " GROUP BY category",
            params,
        ) as cursor:
            cat_rows = await cursor.fetchall()
        by_category = {r["category"]: r["cnt"] for r in cat_rows}

        unc_params = list(params) + [0]
        unc_where = (
            f"{where} AND consolidated = ?" if where else "WHERE consolidated = ?"
        )
        async with self._db.execute(
            f"SELECT COUNT(*) as cnt FROM memories {unc_where}",  # noqa: S608
            unc_params,
        ) as cursor:
            row = await cursor.fetchone()
            unconsolidated_count = row["cnt"]

        async with self._db.execute(
            f"SELECT COUNT(*) as cnt FROM consolidations {where}",  # noqa: S608
            params,
        ) as cursor:
            row = await cursor.fetchone()
            consolidation_count = row["cnt"]

        async with self._db.execute(
            "SELECT name FROM namespaces ORDER BY name"
        ) as cursor:
            ns_rows = await cursor.fetchall()
        namespaces = [r["name"] for r in ns_rows]

        return {
            "total_memories": total_memories,
            "by_category": by_category,
            "unconsolidated_count": unconsolidated_count,
            "consolidation_count": consolidation_count,
            "namespaces": namespaces,
        }

    # ------------------------------------------------------------------
    # Namespaces
    # ------------------------------------------------------------------

    async def list_namespaces(self) -> list[Namespace]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT name, description, created_at FROM namespaces ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            Namespace(
                name=r["name"],
                description=r["description"] or "",
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # File ingestion tracking
    # ------------------------------------------------------------------

    async def check_file_processed(self, path: str) -> bool:
        assert self._db is not None
        async with self._db.execute(
            "SELECT 1 FROM processed_files WHERE path = ?", (path,)
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    async def mark_file_processed(
        self, path: str, namespace: str, content_hash: str
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO processed_files (path, namespace, hash, processed_at)
            VALUES (?, ?, ?, ?)
            """,
            (path, namespace, content_hash, _utc_now()),
        )
