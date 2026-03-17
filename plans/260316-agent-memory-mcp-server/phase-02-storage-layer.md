# Phase 2: Storage Layer (SQLite)

## Context Links
- [Phase 1: Project Setup](./phase-01-project-setup.md)
- [Google AOMA schema](../reports/researcher-agent-memory-systems.md#database-schema-sqlite)

## Overview
- **Priority:** P1 (Critical)
- **Status:** Complete
- **Effort:** 5h (actual: ~5h)
- **Description:** Implement SQLite storage with sqlite-vec for vector search. Concrete class (no premature ABC — extract interface when second backend exists).

## Key Insights
- Google's AOMA uses flat SQLite with no vectors — works up to ~50 memories
- sqlite-vec adds vector similarity search without external dependencies
- Concrete class first; extract ABC only when adding a second backend (YAGNI)
- Namespace-based scoping = just a column filter, not separate databases

## Red Team Findings Applied
- **[RT-4] Embedding dimension metadata**: Store active model + dim in `metadata` table. On startup, compare config vs stored. Refuse to start on mismatch with clear migration options.
- **[RT-12] Dual storage consistency**: Wrap `memories` + `memory_vectors` writes in a single transaction. Drop redundant `embedding` BLOB column — vec0 is the only consumer.

## Requirements

### Functional
- Abstract `StorageAdapter` base class with full CRUD + search
- SQLite implementation with sqlite-vec for vector similarity
- Namespace-based filtering on all operations
- Pagination for list operations
- Consolidation storage (insights, source links)

### Non-Functional
- Thread-safe (async-compatible)
- Auto-migrate schema on startup
- Handle concurrent reads gracefully
- <10ms latency for single memory operations

## Architecture

```python
class SQLiteStorage:
    """Concrete SQLite storage — no ABC until a second backend exists."""
    async def initialize(self) -> None: ...
    async def store(self, memory: Memory) -> str: ...
    async def get(self, memory_id: str) -> Memory | None: ...
    async def update(self, memory_id: str, **fields) -> Memory: ...
    async def delete(self, memory_id: str) -> bool: ...
    async def list(self, namespace: str, limit: int, offset: int) -> list[Memory]: ...
    async def search(self, embedding: list[float], namespace: str, top_k: int) -> list[MemorySearchResult]: ...
    async def get_unconsolidated(self, namespace: str, limit: int) -> list[Memory]: ...
    async def store_consolidation(self, consolidation: Consolidation) -> str: ...
    async def mark_consolidated(self, memory_ids: list[str]) -> None: ...
    async def get_consolidations(self, namespace: str, limit: int) -> list[Consolidation]: ...
    async def get_stats(self, namespace: str | None) -> dict: ...
    async def list_namespaces(self) -> list[Namespace]: ...
    async def close(self) -> None: ...
```

## Related Code Files

### Files to Create
- `src/agent_memory/storage/sqlite.py` — SQLiteStorage concrete class
- `tests/test_storage.py` — storage tests

### Files to Modify
- `src/agent_memory/storage/__init__.py` — export SQLiteStorage

## Implementation Steps

1. Implement `SQLiteStorage` in `sqlite.py` (concrete class, no ABC):

2. Implement `SQLiteStorage`:
   - Use `aiosqlite` for async SQLite access
   - Load `sqlite-vec` extension on connection
   - Schema auto-migration on `initialize()`
   - SQL schema:
     ```sql
     -- [RT-4] Metadata table for embedding model + dimension tracking
     CREATE TABLE IF NOT EXISTS metadata (
         key TEXT PRIMARY KEY,
         value TEXT NOT NULL
     );
     -- On startup: check metadata.embedding_model + metadata.embedding_dim vs config
     -- If mismatch: refuse to start, offer --reindex CLI flag

     CREATE TABLE IF NOT EXISTS memories (
         id TEXT PRIMARY KEY,
         namespace TEXT NOT NULL DEFAULT 'default',
         content TEXT NOT NULL,
         summary TEXT,
         entities TEXT DEFAULT '[]',
         topics TEXT DEFAULT '[]',
         category TEXT DEFAULT 'fact',
         importance REAL DEFAULT 0.5,
         -- [RT-12] No embedding BLOB column — vec0 is sole vector store
         connections TEXT DEFAULT '[]',
         consolidated INTEGER DEFAULT 0,
         created_at TEXT NOT NULL,
         updated_at TEXT NOT NULL
     );
     CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);
     CREATE INDEX IF NOT EXISTS idx_memories_consolidated ON memories(consolidated);

     -- sqlite-vec virtual table for vector search
     CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
         id TEXT PRIMARY KEY,
         embedding float[{dim}]
     );

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
         processed_at TEXT NOT NULL
     );
     ```

3. Implement vector search in SQLite:
   - **[RT-12]** Store embeddings ONLY in `memory_vectors` (vec0) — no redundant BLOB
   - **[RT-12]** Wrap `memories` INSERT + `memory_vectors` INSERT in single transaction
   - Search: query `memory_vectors` for top-K similar, then join with `memories`
   - Graceful fallback: if no embeddings, return recent memories (like Google's approach)

4. **[RT-4]** Implement dimension validation on startup:
   - Read `metadata.embedding_dim` and `metadata.embedding_model` from DB
   - Compare against config values
   - If mismatch: raise error with clear message and migration options
   - If first run: write config values to metadata table

5. Write comprehensive tests:
   - CRUD operations
   - Namespace isolation
   - Vector search (with mock embeddings)
   - Consolidation flow
   - Stats accuracy
   - Edge cases (empty DB, nonexistent IDs)

## Todo List
- [x] Implement `SQLiteStorage` concrete class with aiosqlite
- [x] Add metadata table for embedding model/dim tracking
- [x] Add sqlite-vec vector table and search
- [x] Implement transactional writes (memories + vec0 in single txn)
- [x] Implement dimension validation on startup
- [x] Implement namespace filtering
- [x] Implement consolidation storage (with transaction wrapping)
- [x] Write storage tests
- [x] Test graceful fallback when no embeddings
- [x] Test dimension mismatch detection

## Success Criteria
- All CRUD operations work with namespace isolation
- Vector search returns ranked results by similarity
- Fallback to recency-based when no embeddings exist
- Stats correctly count per-namespace and global
- All tests pass

## Risk Assessment
- **sqlite-vec compilation:** May fail on some platforms. Mitigate: try-except import, fallback to no-vector mode with warning.
- **Embedding dimension mismatch:** Different providers have different dims. Mitigate: configure dim in config, validate on store.
- **Concurrent writes:** SQLite single-writer. Mitigate: use `aiosqlite` with WAL mode enabled.

## Security Considerations
- SQL injection: use parameterized queries everywhere
- DB file permissions: create with `0o600`
- Never log memory content at INFO level (may contain sensitive data)
