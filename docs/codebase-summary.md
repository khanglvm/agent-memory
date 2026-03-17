# Codebase Summary

Total lines of code: ~2,150 (src)
Test coverage: 109 tests across 6 major modules
Python version: 3.11+

## Module Structure

### Root Package: `agent_memory` (3 lines)
- **Purpose:** Package metadata and version export
- **Key Exports:** `__version__ = "0.1.0"`

### CLI & Server Bootstrap: `__main__.py` (148 lines)
- **Purpose:** Entry point for `agent-memory-server` command
- **Key Classes/Functions:**
  - `parse_args()` — Parse CLI arguments (--config, --transport, --host, --port)
  - `run()` — Initialize config, storage, server; handle lifecycle
  - `main()` — Entry point with error handling
- **Key Responsibility:** Wire up config → storage → embedding → consolidation → ingestion → MCP server

### Configuration: `config.py` (154 lines)
- **Purpose:** YAML + env var configuration management
- **Key Classes:**
  - `StorageConfig` — db_path, resolved_db_path() path expansion
  - `EmbeddingConfig` — provider, api_key, model, dimensions, url validation
  - `ConsolidationConfig` — provider, api_key, model, auto_interval_minutes
  - `ServerConfig` — transport (stdio|http), host, port, auth_token
  - `IngestionConfig` — allowed_paths, max_file_size, supported_extensions
  - `MemoryConfig` — Full config with env var override via AGENT_MEMORY_* prefix
  - `load_config()` — Factory; reads YAML, applies env overrides
- **Key Pattern:** Pydantic + custom parsing for nested env vars (__ = nesting)

### Data Models: `models.py` (59 lines)
- **Purpose:** Pydantic schemas for type validation
- **Key Classes:**
  - `Memory` — id, namespace, content, summary, entities, topics, category, importance, connections, consolidated, timestamps
  - `MemorySearchResult` — Memory + similarity score from vector search
  - `Consolidation` — id, namespace, source_ids[], summary, insight, created_at
  - `Namespace` — name, description, created_at
- **Key Helpers:** `_utc_now()`, `_new_id()` for defaults

### MCP Server: `server.py` (378 lines)
- **Purpose:** FastMCP server with 9 tools and 4 resources
- **Key Functions:**
  - `create_mcp_server()` — Wires up all tools and resources
  - Signal handling for graceful shutdown
- **Tools (9):**
  - `store_memory()` — Save memory with optional enrichment
  - `search_memory()` — Semantic search (or recency fallback)
  - `update_memory()` — Modify content/metadata
  - `delete_memory()` — Remove memory by ID
  - `list_memories()` — Paginated listing by namespace
  - `get_memory_stats()` — Count and summary statistics
  - `consolidate_memories()` — Trigger consolidation engine
  - `ingest_text()` — Import text as memory
  - `ingest_file()` — Import file (with path validation)
- **Resources (4):**
  - `memory://stats` — Global statistics
  - `memory://recent/{namespace}` — Last 10 memories
  - `memory://namespaces` — All available namespaces
  - `memory://consolidations/{namespace}` — Recent insights
- **Key Invariants:**
  - MAX_CONTENT_LENGTH = 10,000 chars
  - MAX_RESULTS = 200 per search
  - Graceful error handling with MCP ErrorSchema

### HTTP Client: `http_client.py` (70 lines)
- **Purpose:** Shared async HTTP client for API calls
- **Key Class:**
  - `APIClient` — Wraps httpx with retry logic, bearer token auth
  - Methods: `post()`, `get()` with timeouts and exponential backoff
- **Key Feature:** Automatic API key header injection for embedding/consolidation endpoints

## Storage Module: `storage/`

### SQLite Backend: `storage/sqlite.py` (637 lines)
- **Purpose:** Persistent storage with optional vector search
- **Key Class:** `SQLiteStorage` — Async SQLite backend
  - `initialize()` — Create schema, load sqlite-vec if available
  - `store_memory()` — Insert new memory with optional embedding
  - `search()` — Vector search (if embeddings available) or recency fallback
  - `update_memory()` — Modify memory in-place
  - `delete_memory()` — Remove memory by ID
  - `list_memories()` — Paginated listing per namespace
  - `get_stats()` — Count memories by category/namespace
  - `list_namespaces()` — All available namespaces
  - `store_consolidation()` — Save consolidation results
  - `get_consolidations()` — List recent consolidations per namespace
  - `cleanup_consolidated()` — Delete marked memories (optional)
- **Key Design:**
  - WAL mode for concurrency
  - Per-namespace locks during consolidation
  - Atomic writes for data integrity
  - Graceful degradation if sqlite-vec unavailable
  - SQL injection prevention via column allowlist
- **Schema:**
  - memories (id, namespace, content, summary, entities, topics, category, importance, connections, consolidated, timestamps)
  - memories_vec (id, vector) — Only if sqlite-vec available
  - consolidations (id, namespace, source_ids[], summary, insight, created_at)
  - namespaces (name, description, created_at)

## Embedding Module: `embedding/`

### Base Provider: `embedding/base.py` (27 lines)
- **Purpose:** Abstract interface for embedding providers
- **Key Class:** `EmbeddingProvider` (ABC)
  - `embed()` — Single text to vector
  - `embed_batch()` — Multiple texts in one call
  - `dimensions` property
  - `_validate_dimensions()` — Ensure vector size matches config

### Concrete Providers: `embedding/providers.py` (111 lines)
- **Purpose:** Implementation of OpenAI-compatible and Ollama providers
- **Key Classes:**
  - `OpenAICompatibleProvider` — Works with OpenAI, Ollama, vLLM, LiteLLM, Together, Fireworks
  - `OllamaProvider` — Specialized for local Ollama (inherits from OpenAICompatible)
  - `NoopProvider` — Stub for systems without embeddings (returns empty vectors)
- **Key Factory:**
  - `get_embedding_provider()` — Returns provider based on config

## Consolidation Module: `consolidation/`

### Engine: `consolidation/engine.py` (208 lines)
- **Purpose:** Orchestrates memory analysis, clustering, insight generation
- **Key Class:** `ConsolidationEngine`
  - `consolidate_namespace()` — Main entry point
  - `_cluster_memories()` — Group similar memories by cosine similarity
  - `_generate_insights()` — Call LLM to extract patterns
  - `_store_consolidations()` — Save results atomically
  - `_schedule_auto_consolidation()` — Background task for periodic runs
- **Key Features:**
  - Circuit breaker (threshold: 3 failures) prevents cascading LLM errors
  - Configurable minimum memory count before consolidation
  - Configurable consolidation schedule
  - Multi-layer JSON parsing for LLM response handling
- **Key Invariant:** Consolidation is idempotent; marks source memories as consolidated

### LLM Providers: `consolidation/llm.py` (81 lines)
- **Purpose:** LLM calls for consolidation
- **Key Class:** `LLMProvider`
  - `complete()` — Single completion call with temperature/max_tokens
  - `_build_headers()` — Bearer token for API calls
- **Key Implementations:** OpenAI-compatible and Ollama

### Prompts: `consolidation/prompts.py` (61 lines)
- **Purpose:** Prompt templates and response parsing
- **Key Classes:**
  - `ConsolidationResponse` — Pydantic model for LLM output (patterns[], new_insights[])
  - `CONSOLIDATION_SYSTEM` — System prompt with CDATA injection defense
  - `build_consolidation_prompt()` — Formats memories for LLM
- **Key Security:** XML/CDATA wrapping prevents prompt injection

## Ingestion Module: `ingestion/`

### Processor: `ingestion/processor.py` (189 lines)
- **Purpose:** File and text ingestion with LLM enrichment
- **Key Class:** `IngestionProcessor`
  - `ingest_text()` — Process raw text string
  - `ingest_file()` — Load file with path validation
  - `_enrich_content()` — Optional LLM enrichment (extract entities, topics, summary)
- **Key Features:**
  - Path allowlist validation (symlink resolution)
  - File size limits
  - Extension allowlist
  - Content deduplication by hash
  - Graceful fallback if LLM unavailable
- **Key Security:** Symlink resolution prevents directory traversal

## Cross-Module Dependencies

```
__main__.py
  └─> config.py (load configuration)
  └─> storage/sqlite.py (initialize database)
  └─> embedding/providers.py (create embedding provider)
  └─> consolidation/engine.py (create consolidation engine)
  └─> ingestion/processor.py (create ingestion processor)
  └─> server.py (create MCP server)

server.py
  └─> models.py (Memory, Consolidation, Namespace)
  └─> storage/sqlite.py (store, search, update, delete, consolidate)
  └─> consolidation/engine.py (consolidate_namespace)
  └─> ingestion/processor.py (ingest_text, ingest_file)
  └─> embedding/providers.py (get provider)

consolidation/engine.py
  └─> consolidation/llm.py (complete)
  └─> consolidation/prompts.py (build_consolidation_prompt, parse response)
  └─> storage/sqlite.py (store_consolidation)

ingestion/processor.py
  └─> consolidation/llm.py (optional enrichment)
  └─> storage/sqlite.py (check for duplicates)

storage/sqlite.py
  └─> models.py (Memory, Consolidation, Namespace)
  └─> embedding/providers.py (embed text for storage)
```

## Key Patterns

### Async/Await Throughout
All I/O operations are async (storage, HTTP, embedding calls) to avoid blocking in MCP environment.

### Pluggable Providers
Embedding and LLM providers are swappable via config; NoopProvider allows graceful degradation.

### Configuration Management
Pydantic models with env var override; dotenv-free approach avoids secrets in files.

### Error Handling
MCP ErrorSchema for tool errors; circuit breaker for external API failures.

### Atomicity
SQLite transactions ensure consolidated memories are stored atomically; per-namespace locks prevent race conditions.

## Testing

**Test Files:** 109 tests across 6 modules
- test_config.py — Configuration parsing
- test_storage.py — SQLite CRUD and search
- test_embedding.py — Provider initialization and embedding
- test_consolidation.py — Engine, LLM, prompt generation
- test_ingestion.py — File/text processing
- test_server.py — MCP tool execution

**Coverage:** pytest-cov with respx for HTTP mocking

## File Statistics

| Module | Lines | Purpose |
|--------|-------|---------|
| storage/sqlite.py | 637 | Storage backend |
| server.py | 378 | MCP server |
| consolidation/engine.py | 208 | Consolidation orchestration |
| ingestion/processor.py | 189 | File/text ingestion |
| consolidation/llm.py | 81 | LLM provider wrapper |
| embedding/providers.py | 111 | Embedding providers |
| config.py | 154 | Configuration |
| __main__.py | 148 | CLI entry point |
| consolidation/prompts.py | 61 | Prompt templates |
| models.py | 59 | Pydantic schemas |
| http_client.py | 70 | Async HTTP client |
| embedding/base.py | 27 | Abstract base |
| __init__.py | 3 | Package metadata |

## Code Quality Standards

- **Style:** Black/Ruff (100-char lines, Python 3.11+ features)
- **Type Hints:** Full coverage via Pydantic
- **Error Handling:** Try/catch with circuit breaker for external calls
- **Logging:** Structured logs at DEBUG/INFO/WARN/ERROR levels
- **Testing:** pytest with async support; 95%+ coverage target
- **Security:** OWASP top 10 mitigations (injection, auth, path traversal)
