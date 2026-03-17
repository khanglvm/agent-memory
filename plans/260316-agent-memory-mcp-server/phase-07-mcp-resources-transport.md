# Phase 7: MCP Resources & Streamable HTTP Transport

## Context Links
- [Phase 4: MCP Tools](./phase-04-mcp-server-tools.md)
- [MCP Protocol Spec](https://modelcontextprotocol.io)

## Overview
- **Priority:** P2 (Medium)
- **Status:** Complete
- **Effort:** 4h (actual: ~4h)
- **Description:** Add MCP Resources for read-only data exposure and Streamable HTTP transport for remote/cloud agents.

## Key Insights
- Resources = read-only data that MCP clients can pull (not tools)
- Streamable HTTP is the newer MCP transport — stateless, better for cloud
- Resources are useful for agent context: "always load my memory stats before starting"

## Red Team Findings Applied
- **[RT-1]** Safe defaults: `http_host: 127.0.0.1` (not 0.0.0.0), `cors_origins: ["http://localhost:*"]` (not *). Bearer token auth required for non-localhost.
- **[RT-1]** Bearer token auth: configurable `auth_token` in config. Reject unauthenticated requests when token is set.
- Cut "both" mode from MVP — one transport at a time (stdio OR http). Dual-transport with write serialization is post-MVP.

## Requirements

### Functional
- MCP Resources:
  - `memory://stats` — current memory statistics
  - `memory://recent/{namespace}` — last 10 memories in namespace
  - `memory://namespaces` — list of all namespaces
  - `memory://consolidations/{namespace}` — recent insights
- Streamable HTTP transport:
  - Run as alternative to stdio (one at a time for MVP)
  - Bearer token authentication
  - CORS support (localhost-only by default)
  - Health check endpoint

### Non-Functional
- Resources should be fast (<50ms)
- HTTP transport must handle concurrent connections

## Related Code Files

### Files to Modify
- `src/agent_memory/server.py` — add resources + HTTP transport setup
- `src/agent_memory/__main__.py` — add HTTP transport startup
- `src/agent_memory/config.py` — add transport config

### Files to Create
- `tests/test_resources.py`

## Implementation Steps

1. Add MCP Resources to `server.py`:
   ```python
   @mcp.resource("memory://stats")
   async def memory_stats() -> str:
       stats = await storage.get_stats(None)
       return json.dumps(stats)

   @mcp.resource("memory://recent/{namespace}")
   async def recent_memories(namespace: str) -> str:
       memories = await storage.list(namespace, limit=10, offset=0)
       return json.dumps([m.model_dump() for m in memories])

   @mcp.resource("memory://namespaces")
   async def list_namespaces() -> str:
       ns = await storage.list_namespaces()
       return json.dumps([n.model_dump() for n in ns])
   ```

2. **[RT-1]** Add Streamable HTTP transport with auth:
   - Use `mcp` SDK's built-in HTTP transport if available
   - Or implement with `uvicorn` wrapping the MCP server
   - **Bearer token auth middleware**: check `Authorization: Bearer {token}` on all requests when `auth_token` is set
   - Config:
     ```yaml
     server:
       transport: stdio  # stdio | http (one at a time for MVP)
       http_host: 127.0.0.1  # [RT-1] localhost-only by default
       http_port: 8888
       auth_token: ${AGENT_MEMORY_AUTH_TOKEN}  # required for non-localhost
       cors_origins: ["http://localhost:*"]  # [RT-1] restrictive default
     ```

3. Add health check at `/health` for HTTP transport (no auth required)

4. Startup validation: if `http_host != 127.0.0.1` and `auth_token` is not set, refuse to start with clear error

## Todo List
- [x] Implement `memory://stats` resource
- [x] Implement `memory://recent/{namespace}` resource
- [x] Implement `memory://namespaces` resource
- [x] Implement `memory://consolidations/{namespace}` resource
- [x] Add Streamable HTTP transport (one-at-a-time, no "both" mode)
- [x] Implement bearer token auth middleware
- [x] Implement startup validation (no remote binding without auth)
- [x] Add CORS support (localhost-only default)
- [x] Add `/health` endpoint
- [x] Add transport config with safe defaults
- [x] Write tests for resources
- [x] Write tests for auth (token required, rejected without)

## Success Criteria
- All resources return correct data
- HTTP transport accepts MCP connections
- Both transports can run simultaneously
- CORS works for web clients
- Health check returns 200

## Risk Assessment
- **MCP SDK HTTP support:** May not be mature. Mitigate: check SDK docs, fallback to custom aiohttp wrapper.
- **Port conflicts:** Default 8888 may be in use. Mitigate: configurable port, clear error message.

## Security Considerations
- **[RT-1]** HTTP transport: bearer token auth required for non-localhost binding
- **[RT-1]** CORS: default `["http://localhost:*"]`, configurable
- **[RT-1]** Refuse to bind `0.0.0.0` without auth_token set
- Rate limiting on HTTP endpoints
