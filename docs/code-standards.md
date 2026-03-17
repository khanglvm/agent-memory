# Code Standards & Conventions

Standards and conventions used throughout the agent-memory codebase.

## File Naming & Organization

**File Naming:** kebab-case with descriptive names
```
src/agent_memory/
├── __init__.py              # Package metadata only
├── __main__.py              # CLI entry point
├── config.py                # Configuration classes
├── models.py                # Pydantic schemas
├── server.py                # MCP server implementation
├── http_client.py           # Shared HTTP utilities
├── storage/
│   ├── __init__.py
│   └── sqlite.py            # SQLite backend
├── embedding/
│   ├── __init__.py
│   ├── base.py              # Abstract base
│   └── providers.py         # Concrete implementations
├── consolidation/
│   ├── __init__.py
│   ├── engine.py            # Main orchestration
│   ├── llm.py               # LLM provider wrapper
│   └── prompts.py           # Prompt templates
├── ingestion/
│   ├── __init__.py
│   └── processor.py         # File/text ingestion
└── vault/
    ├── __init__.py
    ├── serializer.py        # Memory <-> Markdown conversion
    ├── writer.py            # Write .md to Obsidian vault
    ├── watcher.py           # Watch vault folder for changes
    └── routes.py            # REST API (Starlette, port 8889)
```

**Directory Structure:**
- One responsibility per module (e.g., sqlite.py for storage, providers.py for embedding)
- Sub-packages for logical groupings (storage/, embedding/, consolidation/, ingestion/)
- Avoid single-use files; combine if <100 lines

## Python Style

**Version:** Python 3.11+

**Formatter/Linter:** Ruff
```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]  # Errors, unused, imports, names, warnings
```

**Key Rules:**
- 100-character line limit
- 4-space indentation (no tabs)
- Two blank lines between top-level class/function definitions
- One blank line between methods
- Trailing commas in multi-line collections

**Type Hints:** Required for all public functions
```python
async def store_memory(
    self,
    memory: Memory
) -> bool:
    """Store a memory and return success status."""
```

**Docstrings:** Google style, triple-quoted
```python
def _parse_llm_json(raw: str) -> ConsolidationResponse:
    """Parse LLM response with multi-layer fallback.

    Attempts JSON parsing in this order:
    1. Direct json.loads
    2. Strip markdown fences
    3. Extract first {...} block
    4. Pydantic validation

    Args:
        raw: Raw LLM output string.

    Returns:
        ConsolidationResponse parsed from JSON.

    Raises:
        ValueError: If no parseable JSON found.
    """
```

**Imports:**
- Organize in 3 groups: stdlib, third-party, local (isort compatible)
- Use absolute imports, not relative
- Avoid `import *`

```python
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agent_memory.models import Memory

if TYPE_CHECKING:
    from agent_memory.storage import SQLiteStorage
```

## Async Patterns

**Async/Await Everywhere:** All I/O operations must be async to prevent blocking in MCP context.

```python
async def initialize(self) -> None:
    """Open database and create schema."""
    async with aiosqlite.connect(path) as db:
        await db.execute(sql)
        await db.commit()
```

**Never:**
- Use `time.sleep()` (use `asyncio.sleep()`)
- Block on sync I/O (use httpx async, aiosqlite, etc.)
- Mix sync/async in same function

**Context Managers:**
```python
async with aiosqlite.connect(path) as db:
    await db.execute(sql)
```

## Configuration Patterns

**Pydantic Models:** All config is validated via Pydantic
```python
from pydantic import BaseModel, Field, field_validator

class EmbeddingConfig(BaseModel):
    provider: str = "openai"
    api_key: str | None = None
    model: str = "text-embedding-3-small"
    dimensions: int = 1536

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("dimensions must be positive")
        return v
```

**Env Var Overrides:** AGENT_MEMORY_* prefix with __ for nesting
```bash
export AGENT_MEMORY_STORAGE__DB_PATH=/custom/path/memory.db
export AGENT_MEMORY_EMBEDDING__PROVIDER=ollama
```

Loaded via:
```python
env_var = os.getenv("AGENT_MEMORY_STORAGE__DB_PATH")
```

**No Dotenv Files:** Configuration via YAML + env vars only; no .env files to avoid committing secrets.

## Error Handling

**Exceptions:** Use built-in exceptions; create custom if necessary
```python
if not path.exists():
    raise FileNotFoundError(f"Config file not found: {path}")

try:
    embedding = await provider.embed(text)
except ValueError as e:
    logger.warning("Embedding failed: %s", e)
    raise
```

**MCP Errors:** Use ErrorSchema for tool errors
```python
@mcp.tool()
async def store_memory(content: str) -> dict:
    try:
        memory = await storage.store_memory(content)
        return {"id": memory.id, "created_at": memory.created_at}
    except Exception as e:
        logger.error("Failed to store memory: %s", e)
        raise ValueError(f"Storage failed: {e}") from e
```

**Circuit Breaker:** Prevent cascading LLM failures
```python
if self._circuit_breaker_open:
    logger.info("Circuit breaker open; skipping consolidation")
    return []

try:
    result = await llm.complete(prompt)
except Exception:
    self._failure_count += 1
    if self._failure_count >= _CIRCUIT_BREAKER_THRESHOLD:
        self._circuit_breaker_open = True
    raise
```

## Security Patterns

**SQL Injection Prevention:** Use parameterized queries only
```python
# Good
await db.execute(
    "SELECT * FROM memories WHERE namespace = ? AND id = ?",
    (namespace, memory_id)
)

# Bad - never use string interpolation
await db.execute(f"SELECT * FROM memories WHERE namespace = '{namespace}'")
```

**Column Allowlist:** Only allow specific columns in WHERE/ORDER BY
```python
_ALLOWED_COLUMNS = {"created_at", "updated_at", "importance", "category"}

def _validate_sort_column(col: str) -> None:
    if col not in _ALLOWED_COLUMNS:
        raise ValueError(f"Invalid sort column: {col}")
```

**Prompt Injection Defense:** Wrap user input in XML/CDATA tags
```python
prompt = f"""
<memories>
<![CDATA[
{memory_content}
]]>
</memories>

Extract patterns from the memories above.
"""
```

**Path Traversal Prevention:** Resolve symlinks and validate allowlist
```python
allowed_paths = [Path(p).resolve() for p in config.allowed_paths]
requested_path = Path(filepath).resolve()

if not any(requested_path.is_relative_to(ap) for ap in allowed_paths):
    raise ValueError(f"Path not in allowlist: {filepath}")
```

**Bearer Token Auth:** Required for non-localhost HTTP
```python
headers = {}
if auth_token:
    headers["Authorization"] = f"Bearer {auth_token}"
```

## Testing Patterns

**Test File Organization:**
```
tests/
├── conftest.py              # Shared fixtures
├── test_config.py
├── test_storage.py
├── test_embedding.py
├── test_consolidation.py
├── test_ingestion.py
└── test_server.py
```

**Async Tests:** Use pytest-asyncio
```python
@pytest.mark.asyncio
async def test_store_memory():
    storage = SQLiteStorage(config)
    await storage.initialize()

    memory = Memory(content="Test fact")
    result = await storage.store_memory(memory)
    assert result is True
```

**Fixtures:** Shared setup in conftest.py
```python
@pytest.fixture
async def storage(tmp_path: Path) -> SQLiteStorage:
    config = StorageConfig(db_path=str(tmp_path / "test.db"))
    storage = SQLiteStorage(config)
    await storage.initialize()
    yield storage
    await storage.close()
```

**HTTP Mocking:** Use respx for API mocks
```python
import respx

@pytest.mark.asyncio
async def test_embedding():
    with respx.mock:
        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(200, json={
                "data": [{"embedding": [0.1, 0.2, 0.3]}]
            })
        )
        provider = OpenAICompatibleProvider(...)
        vector = await provider.embed("test")
        assert len(vector) == 3
```

**Edge Cases:**
- Test with empty inputs (empty string, empty list)
- Test with large inputs (10K+ char memory)
- Test with special characters (quotes, newlines, unicode)
- Test async cleanup (ensure resources freed)

## Logging Patterns

**Logger Setup:** One logger per module
```python
import logging

logger = logging.getLogger(__name__)
```

**Log Levels:**
- DEBUG — Detailed flow (function entry/exit, variable values)
- INFO — Normal operation (server started, memory stored)
- WARNING — Unexpected but recoverable (embedding failed, fallback to recency)
- ERROR — Failures requiring investigation (database error, LLM parse failure)

```python
logger.debug("Searching memories in namespace: %s", namespace)
logger.info("Memory stored: %s", memory.id)
logger.warning("Embedding provider failed: %s, using recency search", error)
logger.error("Failed to parse LLM response: %s", error)
```

**Structured Logging:** Avoid string formatting in log messages
```python
# Good
logger.error("Memory store failed", exc_info=True)

# Less ideal
logger.error(f"Memory store failed: {e}")
```

## API Design (MCP Tools)

**Tool Naming:** snake_case, verb_noun pattern
```python
@mcp.tool()
async def store_memory(content: str, namespace: str = "default") -> dict:
    """Store a new memory."""
```

**Input Validation:** Check limits before processing
```python
if len(content) > MAX_CONTENT_LENGTH:
    content = content[:MAX_CONTENT_LENGTH]
    logger.warning("Content truncated to %d chars", MAX_CONTENT_LENGTH)
```

**Return Format:** Always dict for tools, always describe in docstring
```python
@mcp.tool()
async def search_memory(query: str, limit: int = 10) -> dict:
    """Search memories by semantic similarity.

    Args:
        query: Search query text.
        limit: Maximum results (default 10, max 200).

    Returns:
        {
            "results": [
                {"id": str, "content": str, "similarity": float},
                ...
            ],
            "count": int
        }
    """
```

## Constants & Magic Numbers

**Define as Module Constants:** Avoid scattered magic numbers
```python
# At module top
_MAX_CONTENT_LENGTH = 10_000
_MAX_RESULTS = 200
_CIRCUIT_BREAKER_THRESHOLD = 3
_DB_TIMEOUT = 30.0

# Usage
if len(content) > _MAX_CONTENT_LENGTH:
    content = content[:_MAX_CONTENT_LENGTH]
```

## Performance Considerations

**Batch Operations:** Use batch methods for multiple items
```python
# Good
vectors = await provider.embed_batch(texts)

# Avoid
vectors = [await provider.embed(text) for text in texts]
```

**Lazy Loading:** Don't load all memories at once
```python
# Good (pagination)
memories = await storage.list_memories(namespace, limit=10, offset=0)

# Avoid
all_memories = await storage.get_all()  # Never implement this
```

**Vector Search Dimension Check:** Validate early to prevent cascading errors
```python
def _validate_dimensions(self, vector: list[float]) -> None:
    if len(vector) != self._embedding_dim:
        raise ValueError(
            f"Expected {self._embedding_dim} dimensions, got {len(vector)}"
        )
```

## Breaking Changes

**Versioning:** Semantic versioning (MAJOR.MINOR.PATCH)
- MAJOR: Breaking API changes
- MINOR: New features, backward compatible
- PATCH: Bug fixes

**Deprecation:** Phase out gradually with warnings
```python
import warnings

def old_method():
    warnings.warn(
        "old_method is deprecated; use new_method instead",
        DeprecationWarning,
        stacklevel=2
    )
```

## Common Mistakes to Avoid

1. **Blocking I/O in Async Functions** — Use async libraries only
2. **String Interpolation in Queries** — Always use parameterized queries
3. **Bare Exception Handlers** — Specify exception types: `except ValueError:`
4. **Mutable Default Arguments** — Use `None` and initialize in function body
5. **Logging Secrets** — Never log API keys, tokens, or sensitive data
6. **Ignoring Exceptions** — At minimum, log them
7. **Circular Imports** — Use TYPE_CHECKING guards
8. **Hardcoded Paths** — Use pathlib.Path and env overrides

## Review Checklist

Before submitting a PR:
- [ ] All functions have type hints and docstrings
- [ ] No f-strings in log messages
- [ ] No blocking I/O in async functions
- [ ] All public APIs have examples in tests
- [ ] Circuit breaker/retry logic for external calls
- [ ] Security patterns (parameterized queries, path validation)
- [ ] New dependencies added to pyproject.toml
- [ ] Tests pass (pytest tests/ -v)
- [ ] Linting passes (ruff check src/ tests/)
- [ ] No secrets in comments or config examples
