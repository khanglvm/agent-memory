# Agent Memory

Persistent memory system for AI agents. Store, search, and consolidate knowledge across sessions via an MCP server.

Works with any MCP-compatible client: Claude Code, Cursor, Windsurf, Cline, or custom agents.

```
pip install agent-memory-server
```

## Quick Start

### For Claude Code Users

```bash
# 1. Add the MCP server
claude mcp add --transport stdio agent-memory -- uvx agent-memory-server

# 2. Install the agent skill (teaches Claude when to use memory)
npx skills add khanglvm/agent-memory -g
```

### For Other Clients

Configure in your client's MCP settings:
```json
{
  "mcpServers": {
    "agent-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["agent-memory-server"]
    }
  }
}
```

## Features

**9 Tools** for memory management:
- `store_memory` — Save facts, preferences, procedures, episodes
- `search_memory` — Semantic search across memories
- `update_memory` — Modify existing memories
- `delete_memory` — Remove outdated memories
- `list_memories` — Browse memories by namespace
- `get_memory_stats` — View statistics
- `consolidate_memories` — Find patterns and insights
- `ingest_text` — Ingest raw text
- `ingest_file` — Ingest files (within allowed paths)

**4 Resources** for read-only access:
- `memory://stats` — Global statistics
- `memory://recent/{namespace}` — Last 10 memories
- `memory://namespaces` — All namespaces
- `memory://consolidations/{namespace}` — Recent insights

Organize memories by **namespace** (e.g., `global`, `project:myapp`) and **category** (fact, preference, procedure, episode).

## Installation

**Via pip:**
```bash
pip install agent-memory-server
```

**From source:**
```bash
git clone https://github.com/khanglvm/agent-memory.git
cd agent-memory
pip install -e ".[dev]"
```

**With custom config:**
```bash
agent-memory-server --config ~/.agent-memory/config.yaml
```

## Configuration

**Zero-config default:** SQLite at `~/.agent-memory/memory.db` with recency search.

Enable semantic search with embedding provider:
```yaml
embedding:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: text-embedding-3-small

consolidation:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o-mini
```

**Alternatives:** Ollama (local, no API key) or disable embeddings entirely.

Environment variables override config with `AGENT_MEMORY_` prefix:
```bash
export AGENT_MEMORY_EMBEDDING__PROVIDER=ollama
export AGENT_MEMORY_SERVER__TRANSPORT=http
```

## Transport

**Default:** stdio (used by MCP clients).

**HTTP mode** for remote agents:
```bash
agent-memory-server --transport http --host 0.0.0.0 --port 8888
```

Requires bearer token for non-localhost:
```bash
AGENT_MEMORY_AUTH_TOKEN=secret agent-memory-server --transport http --host 0.0.0.0
```

## Architecture

Three layers:
- **API Layer:** 9 MCP tools + 4 resources via stdio or HTTP
- **Processing:** Pluggable embedding providers (OpenAI/Ollama/None) and consolidation LLMs
- **Storage:** SQLite + sqlite-vec for vector search, automatic fallback to recency search

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v          # Run tests
ruff check src/ tests/    # Lint
python -m agent_memory    # Run server
```

## Documentation

- [Project Overview & PDR](./docs/project-overview-pdr.md) — Vision, features, metrics
- [System Architecture](./docs/system-architecture.md) — Design, data flow, security
- [Code Standards](./docs/code-standards.md) — Style, patterns, testing
- [Deployment Guide](./docs/deployment-guide.md) — Installation, config, troubleshooting
- [Codebase Summary](./docs/codebase-summary.md) — Module reference
- [Roadmap](./docs/project-roadmap.md) — Status and future direction

## License

MIT
