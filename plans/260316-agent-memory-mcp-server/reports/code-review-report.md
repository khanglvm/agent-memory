# Code Review Report: agent-memory MCP Server

**Date:** 2026-03-16
**Reviewer:** code-reviewer
**Scope:** 12 files, ~1150 LOC across config, models, server, storage, embedding, consolidation, ingestion

---

## Overall Assessment

The codebase is well-structured with clear separation of concerns, good use of Pydantic for validation, proper async patterns, and evidence of red-team hardening (RT-1 through RT-15 references). Most security-critical paths use parameterized queries and input validation. Several medium-severity gaps remain.

---

## Critical Issues

None found. The codebase handles the critical security surface well: parameterized SQL, HTTPS enforcement for API keys, path traversal defense with `resolve()`, prompt injection mitigation via CDATA wrapping.

---

## High Priority

### H-1: Consolidation LLM provider does not pass `allow_insecure` to APIClient

**File:** `src/agent_memory/consolidation/llm.py:74-78`

The `create_llm_provider()` factory creates an `APIClient` for the OpenAI-compatible provider but does NOT pass `allow_insecure` from config. The `ConsolidationConfig` model also lacks an `allow_insecure` field entirely. If a user configures consolidation with an API key and an HTTP base_url (e.g., local LiteLLM proxy), `APIClient.__init__` will raise an error with no way to override.

Meanwhile, `EmbeddingConfig` correctly has `allow_insecure` and passes it through.

**Fix:** Add `allow_insecure: bool = False` to `ConsolidationConfig` and pass it to `APIClient` in `create_llm_provider()`.

### H-2: `update()` uses dynamic f-string column names without allowlist

**File:** `src/agent_memory/storage/sqlite.py:290-296`

```python
set_clause = ", ".join(f"{k} = ?" for k in fields)
```

While the `noqa: S608` suppression acknowledges this, the field names come from `**fields` which originates from `server.py`'s `update_memory()`. Currently the server only passes `content`, `importance`, `category`, `new_embedding`, and `updated_at` -- but there is no allowlist enforcing this at the storage layer. If a new caller passes arbitrary keys, this becomes a SQL injection vector via column name.

**Fix:** Add a column allowlist in `update()`:
```python
_UPDATABLE_COLUMNS = {"content", "summary", "entities", "topics", "category",
                      "importance", "connections", "consolidated", "updated_at"}
invalid = set(fields) - _UPDATABLE_COLUMNS - {"new_embedding"}
if invalid:
    raise ValueError(f"Invalid update fields: {invalid}")
```

### H-3: No upper bound on `top_k`, `limit`, `offset` parameters

**File:** `src/agent_memory/server.py` (lines 112, 211-212)

`top_k` and `limit` are passed directly to SQL `LIMIT` with no max cap. A caller could pass `top_k=1000000` and force a full table scan + massive memory allocation. `offset` has no bounds either (negative values are technically accepted by SQLite but semantically wrong).

**Fix:** Clamp in the tool handlers:
```python
top_k = max(1, min(top_k, 100))
limit = max(1, min(limit, 100))
offset = max(0, offset)
```

---

## Medium Priority

### M-1: Auto-consolidation task not tracked -- fire-and-forget

**File:** `src/agent_memory/__main__.py:121`

```python
asyncio.create_task(consolidation_engine.start_auto_consolidation())
```

The task reference is not stored. If the coroutine raises an unexpected exception (not caught by the internal try/except), the task dies silently. Python will log a "Task exception was never retrieved" warning at GC time, but this is unreliable.

**Fix:** Store the task and add an exception callback:
```python
auto_task = asyncio.create_task(consolidation_engine.start_auto_consolidation())
auto_task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)
```

### M-2: `_get_lock()` is not thread-safe for multi-event-loop scenarios

**File:** `src/agent_memory/consolidation/engine.py:82-85`

```python
def _get_lock(self, namespace: str) -> asyncio.Lock:
    if namespace not in self._locks:
        self._locks[namespace] = asyncio.Lock()
    return self._locks[namespace]
```

The check-then-set is not atomic. In a single event loop this is fine, but if the engine were ever shared across threads, this would race. Low risk in current architecture but worth a `setdefault` for defensive coding:

```python
return self._locks.setdefault(namespace, asyncio.Lock())
```

### M-3: `delete()` is not transactional

**File:** `src/agent_memory/storage/sqlite.py:309-318`

Deleting from `memories` and `memory_vectors` are two separate operations without a transaction. If the process crashes between them, the vector entry becomes orphaned (no matching memory row).

**Fix:** Wrap in BEGIN/COMMIT like `store()` does.

### M-4: Signal handlers set in non-main thread may fail

**File:** `src/agent_memory/server.py:54-55`

`signal.signal()` must be called from the main thread. If `create_mcp_server()` is ever called from a non-main thread (e.g., in tests or embedded use), this raises `ValueError`. Consider guarding with a try/except or checking `threading.current_thread() is threading.main_thread()`.

### M-5: File dedup checks path but not content hash

**File:** `src/agent_memory/ingestion/processor.py:151-157`

`check_file_processed()` only checks if the path exists in `processed_files`. If the file content changes (same path, different hash), the ingestion is rejected. The content hash is stored but never compared for re-ingestion on update.

**Fix:** Compare stored hash vs current hash; if different, allow re-ingestion and update the record.

### M-6: Auto-consolidation only processes "default" namespace

**File:** `src/agent_memory/consolidation/engine.py:165`

```python
namespace = "default"
```

The auto-consolidation loop hardcodes the namespace to "default". Memories in other namespaces will never be auto-consolidated. If multiple namespaces are used, this is a functional gap.

### M-7: `_parse_llm_json` regex may match nested braces greedily

**File:** `src/agent_memory/consolidation/engine.py:28`

```python
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.DOTALL)
```

The `*` is greedy, so for output like `{...} some text {...}` it matches from the first `{` to the last `}` -- which may include invalid content between two JSON objects. Consider using `*?` (lazy) or a proper brace-depth counter.

Same issue in `src/agent_memory/ingestion/processor.py:27`.

---

## Low Priority

### L-1: Ollama provider does not validate embedding dimensions

**File:** `src/agent_memory/embedding/providers.py:71-81`

`OpenAICompatibleProvider` validates dimensions after each embed call, but `OllamaProvider` does not. A misconfigured dimension will only surface as a sqlite-vec error on storage.

### L-2: Duplicate `_utc_now()` definition

**File:** `models.py:11` and `storage/sqlite.py:26`

Same function defined in two places. Extract to a shared `utils.py`.

### L-3: `APIClient` does not close on error paths

**File:** `src/agent_memory/http_client.py`

If the caller never calls `close()`, the `httpx.AsyncClient` leaks. Consider implementing `__aenter__`/`__aexit__` or adding a `__del__` safety net. The embedding and LLM providers hold `APIClient` instances but have no `close()` lifecycle.

---

## Positive Observations

1. **RT-15 HTTPS enforcement** in `APIClient` is solid -- blocks HTTP when API keys are present.
2. **RT-2 prompt injection defense** uses CDATA wrapping with proper `]]>` escaping.
3. **RT-5 transactional consolidation** -- `store_consolidation()` atomically marks source memories.
4. **RT-6 per-namespace locking** prevents concurrent consolidation races.
5. **RT-7 multi-layer JSON parsing** handles LLM output variability gracefully.
6. **Circuit breaker** in auto-consolidation prevents runaway failure loops.
7. **Path traversal defense** uses `resolve()` + `relative_to()` with symlink resolution.
8. **Parameterized SQL** used consistently -- no string interpolation of user values.
9. **WAL mode** for SQLite -- good concurrency characteristics.
10. **Pydantic validation** throughout for config and data models.

---

## Recommended Actions (Priority Order)

1. **H-2**: Add column allowlist to `update()` -- prevents future SQL injection via column names
2. **H-1**: Add `allow_insecure` to `ConsolidationConfig` for parity with embedding config
3. **H-3**: Clamp `top_k`/`limit`/`offset` to reasonable bounds
4. **M-3**: Wrap `delete()` in a transaction
5. **M-5**: Compare content hash on re-ingestion to support file updates
6. **M-6**: Iterate all namespaces in auto-consolidation loop
7. **M-7**: Switch regex to lazy matching for JSON block extraction

---

## Metrics

- Type Coverage: ~90% (good use of type hints; `object | None` for llm_provider in IngestionProcessor is loose)
- Test Coverage: Test files exist for all major modules (not executed in this review)
- Linting Issues: Multiple `noqa: S608` suppressions for dynamic SQL -- acceptable given parameterized values, except H-2

---

## Unresolved Questions

1. Is there an auth middleware for the HTTP/SSE transport, or does FastMCP handle bearer token validation internally?
2. Should the `processed_files` table track memory_id to enable proper re-ingestion when content changes?
3. Is there a plan for embedding provider resource cleanup (APIClient.close()) on server shutdown?
