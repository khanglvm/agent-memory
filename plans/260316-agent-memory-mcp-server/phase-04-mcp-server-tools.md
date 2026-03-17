# Phase 4: MCP Server & Memory Tools

## Context Links
- [Phase 2: Storage](./phase-02-storage-layer.md)
- [Phase 3: Embeddings](./phase-03-embedding-providers.md)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## Overview
- **Priority:** P1 (Critical)
- **Status:** Complete
- **Effort:** 4h (actual: ~4h)
- **Description:** Core MCP server with memory tools. This is the heart of the system — what agents actually interact with.

## Key Insights
- FastMCP is the standard way to build Python MCP servers
- Tools should be self-descriptive (good names, descriptions, typed params)
- Keep tool count manageable — agents work better with fewer, well-designed tools
- Every tool must validate inputs and return structured results

## Red Team Findings Applied
- **[RT-14]** Implement graceful shutdown manager: register background tasks, handle SIGINT/SIGTERM, let in-progress ops complete with timeout, use `asyncio.shield` for critical DB writes.

## Requirements

### Functional
- MCP server with stdio transport (default)
- Core memory tools: store, search, update, delete, list, stats
- All tools namespace-aware
- Structured return types (JSON)
- Error handling with meaningful messages

### Non-Functional
- <100ms response for simple operations
- Clear tool descriptions that guide agent behavior
- Idempotent where possible

## Architecture

```
MCP Client (Claude Code, Cursor, etc.)
    │
    │  stdio / JSON-RPC
    ▼
FastMCP Server
    │
    ├── store_memory(content, namespace, category, tags, importance)
    ├── search_memory(query, namespace, top_k, category)
    ├── update_memory(memory_id, content, importance, category)
    ├── delete_memory(memory_id)
    ├── list_memories(namespace, limit, offset, category)
    └── get_memory_stats(namespace)
    │
    ├── EmbeddingProvider.embed()
    └── StorageAdapter.store/search/...()
```

## Related Code Files

### Files to Create
- `src/agent_memory/server.py` — MCP server with all tools

### Files to Modify
- `src/agent_memory/__main__.py` — wire server startup

## Implementation Steps

1. Create `server.py` with FastMCP:
   ```python
   from mcp.server.fastmcp import FastMCP

   mcp = FastMCP("agent-memory",
       instructions="Memory system for AI agents. Store facts, search knowledge, track insights across sessions.")
   ```

2. Implement `store_memory` tool:
   - Params: content (str, required), namespace (str, default "default"), category (str, enum: fact/preference/procedure/episode), tags (list[str]), importance (float 0-1)
   - Generate embedding if provider configured
   - Store via adapter
   - Return: memory_id, summary confirmation

3. Implement `search_memory` tool:
   - Params: query (str, required), namespace (str), top_k (int, default 10), category (str, optional filter)
   - Embed query → vector search → return ranked results
   - Fallback: if no embeddings, return recent memories matching namespace/category
   - Return: list of {id, content, summary, similarity, category, created_at}

4. Implement `update_memory` tool:
   - Params: memory_id (str, required), content (str), importance (float), category (str)
   - Re-embed if content changed
   - Return: updated memory

5. Implement `delete_memory` tool:
   - Params: memory_id (str, required)
   - Return: confirmation or not_found

6. Implement `list_memories` tool:
   - Params: namespace (str), limit (int, default 20), offset (int, default 0), category (str)
   - Return: paginated list with total count

7. Implement `get_memory_stats` tool:
   - Params: namespace (str, optional — if omitted, global stats)
   - Return: total_memories, by_category counts, unconsolidated count, consolidation count, namespaces

8. Wire server startup in `__main__.py`:
   - Load config → create adapter → create embedding provider → create server
   - Pass adapter + provider to server via dependency injection
   - Start MCP server with configured transport

## Todo List
- [x] Create FastMCP server instance
- [x] Implement `store_memory` tool
- [x] Implement `search_memory` tool with vector + fallback
- [x] Implement `update_memory` tool
- [x] Implement `delete_memory` tool
- [x] Implement `list_memories` tool with pagination
- [x] Implement `get_memory_stats` tool
- [x] Wire server startup in `__main__.py`
- [x] **[RT-14]** Implement shutdown manager (SIGINT/SIGTERM, task drain, asyncio.shield)
- [x] Test all tools with mock storage + embedding

## Success Criteria
- Server starts and responds to MCP protocol
- All 6 tools discoverable by MCP clients
- store → search round-trip returns stored memory
- Namespace isolation verified
- Works with `NoopProvider` (no embeddings)
- `mcp dev` inspector shows all tools

## Risk Assessment
- **Tool naming:** Agents may misuse tools. Mitigate: descriptive names + good instruction text.
- **Large payloads:** Storing very long content. Mitigate: truncate at configurable max (default 10K chars).

## Security Considerations
- Validate all inputs (Pydantic)
- Sanitize content before storage
- No shell execution from tool inputs
- Rate limit consideration for HTTP transport
