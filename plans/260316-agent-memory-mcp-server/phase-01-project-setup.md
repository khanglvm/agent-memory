# Phase 1: Project Setup & Core Structure

## Context Links
- [Research Report](../reports/researcher-agent-memory-systems.md)
- [Google AOMA Reference](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/agents/always-on-memory-agent)

## Overview
- **Priority:** P1 (Critical)
- **Status:** Complete
- **Effort:** 3h (actual: ~3h)
- **Description:** Bootstrap Python project, dependencies, config system, and directory structure.

## Key Insights
- FastMCP SDK is the standard for Python MCP servers
- Config should be YAML/TOML + env vars for flexibility
- Project must be installable as a package (`pip install -e .`)

## Requirements

### Functional
- Python 3.11+ project with `pyproject.toml`
- Config system supporting YAML file + env var overrides
- Logging setup (structured, configurable level)
- CLI entry point for running the server

### Non-Functional
- Zero-config startup with sensible defaults (SQLite, no embeddings required)
- All secrets via env vars, never in config files

## Architecture

```
agent-memory/
├── pyproject.toml
├── README.md
├── config.example.yaml
├── src/
│   └── agent_memory/
│       ├── __init__.py
│       ├── __main__.py          # CLI entry point
│       ├── config.py            # Config loading (YAML + env)
│       ├── models.py            # Data models (Memory, Consolidation, Namespace)
│       ├── http_client.py       # Shared APIClient (Phase 3) [RT-15]
│       ├── server.py            # MCP server setup (Phase 4)
│       ├── storage/
│       │   ├── __init__.py
│       │   └── sqlite.py        # SQLiteStorage concrete class (Phase 2)
│       ├── embedding/
│       │   ├── __init__.py
│       │   ├── base.py          # EmbeddingProvider ABC
│       │   └── providers.py     # OpenAI, Ollama, custom (Phase 3)
│       ├── consolidation/
│       │   ├── __init__.py
│       │   ├── engine.py        # Consolidation engine (Phase 5)
│       │   ├── llm.py           # LLM providers (Phase 5)
│       │   └── prompts.py       # Consolidation prompts (Phase 5)
│       └── ingestion/
│           ├── __init__.py
│           └── processor.py     # Text ingestion (Phase 6)
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_storage.py
│   ├── test_embedding.py
│   ├── test_server.py
│   └── test_consolidation.py
└── plans/
```

## Related Code Files

### Files to Create
- `pyproject.toml` — project metadata, dependencies, entry points
- `config.example.yaml` — example configuration
- `src/agent_memory/__init__.py` — package init with version
- `src/agent_memory/__main__.py` — CLI entry point
- `src/agent_memory/config.py` — config loading system
- `src/agent_memory/models.py` — data models (Pydantic)

## Implementation Steps

1. Create `pyproject.toml` with dependencies:
   - `mcp[cli]` — MCP SDK with CLI tools
   - `pydantic>=2.0` — data validation
   - `pyyaml` — config loading
   - `sqlite-vec` — vector extension
   - `aiohttp` — HTTP transport
   - `httpx` — HTTP client for embedding/LLM providers
   - Dev deps: `pytest`, `pytest-asyncio`, `ruff`

2. Create `config.py`:
   - `MemoryConfig` pydantic model with sections: storage, embedding, consolidation, server
   - Load order: defaults → YAML file → env vars (prefix `AGENT_MEMORY_`)
   - Config file path: `--config` CLI flag or `AGENT_MEMORY_CONFIG` env var
   - Defaults: SQLite storage at `~/.agent-memory/memory.db`, no embeddings, no consolidation

3. Create `models.py`:
   - `Memory` — id (UUID), namespace, content, summary, entities, topics, category, importance, embedding (optional bytes), connections, consolidated, created_at, updated_at
   - `Consolidation` — id, source_ids, summary, insight, created_at
   - `Namespace` — name, description, created_at
   - `MemorySearchResult` — memory + similarity score

4. Create `__main__.py`:
   - `argparse` CLI: `--config`, `--transport` (stdio/http), `--port`, `--host`
   - Wire up config → server startup

5. Create empty `__init__.py` files for all subpackages
6. Create `tests/conftest.py` with shared fixtures

## Todo List
- [x] Create `pyproject.toml` with all dependencies
- [x] Create directory structure with `__init__.py` files
- [x] Implement `config.py` with YAML + env var loading
- [x] Implement `models.py` with Pydantic models
- [x] Implement `__main__.py` CLI entry point
- [x] Create `config.example.yaml`
- [x] Create `tests/conftest.py`
- [x] Verify `pip install -e .` works

## Success Criteria
- `pip install -e .` succeeds
- `python -m agent_memory --help` shows CLI options
- Config loads from YAML with env var overrides
- All data models validate correctly
- `ruff check` passes

## Risk Assessment
- **sqlite-vec availability:** May need compilation on some platforms. Mitigate: document build deps, provide fallback without vector search.
- **Config complexity creep:** Keep config minimal. YAGNI — only add fields needed by current phases.

## Security Considerations
- Never store API keys in YAML config — env vars only
- Config file permissions should be user-readable only
- Log redaction for sensitive values

## Next Steps
- Phase 2 depends on models.py being complete
- Phase 3 depends on config.py being complete
