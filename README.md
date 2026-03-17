# Agent Memory

Persistent memory for AI agents. Store, search, and consolidate knowledge across sessions.

Works with any MCP-compatible client: **Claude Code**, **Cursor**, **Windsurf**, **Cline**, or custom agents.

```
pip install agent-memory-server
```

## Quick Start (Claude Code)

**1. Add the MCP server** (zero-config, works immediately):

```bash
claude mcp add --transport stdio agent-memory -- uvx agent-memory-server
```

**2. Install the agent skill** (teaches Claude _when_ and _how_ to use memory):

```bash
npx skills add khang/agent-memory -g
```

Done. Claude Code now has persistent memory. It will automatically store facts, search past knowledge, and consolidate insights.

---

## What It Does

| Tool | Purpose |
|------|---------|
| `store_memory` | Save facts, preferences, procedures, episodes |
| `search_memory` | Semantic search across all memories |
| `update_memory` | Modify existing memories |
| `delete_memory` | Remove outdated memories |
| `list_memories` | Browse memories by namespace |
| `get_memory_stats` | View memory statistics |
| `consolidate_memories` | Find patterns and generate insights |
| `ingest_text` | Ingest raw text as memory |
| `ingest_file` | Ingest files (within allowed paths) |

Memories are organized by **namespace** (`global`, `project:myapp`, `user:alice`) and **category** (`fact`, `preference`, `procedure`, `episode`).

---

## Installation Options

### Option A: uvx (recommended, zero-install)

```bash
# Claude Code
claude mcp add --transport stdio agent-memory -- uvx agent-memory-server

# Or with config file
claude mcp add --transport stdio agent-memory -- uvx agent-memory-server --config ~/.agent-memory/config.yaml
```

### Option B: pip install

```bash
pip install agent-memory-server

# Then add to Claude Code
claude mcp add --transport stdio agent-memory -- agent-memory-server
```

### Option C: From source

```bash
git clone https://github.com/khang/agent-memory.git
cd agent-memory
pip install -e ".[dev]"

claude mcp add --transport stdio agent-memory -- python -m agent_memory
```

### MCP JSON Config (manual)

If you prefer editing config files directly, add to `.mcp.json` (project) or `~/.claude.json` (global):

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

With config file and environment variables:

```json
{
  "mcpServers": {
    "agent-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["agent-memory-server", "--config", "~/.agent-memory/config.yaml"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
      }
    }
  }
}
```

---

## Agent Skill

The agent skill teaches your AI agent _when_ to store, _what_ to search, and _how_ to namespace memories effectively.

```bash
# Install globally (all projects)
npx skills add khang/agent-memory -g

# Install for current project only
npx skills add khang/agent-memory
```

Without the skill, Claude Code can still use the MCP tools — but with the skill, it knows best practices like:
- Search memory before starting tasks
- Use `project:{name}` namespaces for scoping
- Consolidate after 5+ new memories
- Store session summaries as episodes

---

## Configuration

The server works with **zero configuration** — it uses SQLite at `~/.agent-memory/memory.db` with recency-based search (no embeddings needed).

For semantic search and consolidation, create `~/.agent-memory/config.yaml`:

```yaml
embedding:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: text-embedding-3-small
  dimensions: 1536

consolidation:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o-mini
```

### All Config Options

```yaml
storage:
  db_path: ~/.agent-memory/memory.db     # SQLite database location

embedding:
  provider: openai       # openai | ollama | none
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}
  model: text-embedding-3-small
  dimensions: 1536

consolidation:
  provider: openai       # openai | ollama | none
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o-mini
  auto_interval_minutes: 0   # 0 = manual only
  min_memories: 3

server:
  transport: stdio       # stdio | http
  http_host: 127.0.0.1
  http_port: 8888
  auth_token: ${AGENT_MEMORY_AUTH_TOKEN}   # required for non-localhost HTTP

ingestion:
  allowed_paths: []      # directories allowed for ingest_file (empty = disabled)
  max_file_size_mb: 1
  supported_extensions: [.txt, .md, .json, .csv, .yaml, .yml, .xml, .log]

log_level: INFO
```

### Environment Variable Overrides

Any config value can be set via env var with `AGENT_MEMORY_` prefix and `__` for nesting:

```bash
export AGENT_MEMORY_STORAGE__DB_PATH=/custom/path/memory.db
export AGENT_MEMORY_EMBEDDING__PROVIDER=ollama
export AGENT_MEMORY_LOG_LEVEL=DEBUG
```

### Using with Ollama (local, no API key needed)

```yaml
embedding:
  provider: ollama
  base_url: http://localhost:11434
  model: nomic-embed-text
  dimensions: 768

consolidation:
  provider: ollama
  base_url: http://localhost:11434
  model: llama3.2
```

---

## MCP Resources

Read-only data your agent can pull for context:

| URI | Returns |
|-----|---------|
| `memory://stats` | Global statistics |
| `memory://recent/{namespace}` | Last 10 memories |
| `memory://namespaces` | All namespaces |
| `memory://consolidations/{namespace}` | Recent insights |

---

## HTTP Transport

For remote or cloud agents, run as an HTTP server:

```bash
agent-memory-server --transport http --host 127.0.0.1 --port 8888
```

Non-localhost binding requires `auth_token`:

```bash
AGENT_MEMORY_AUTH_TOKEN=your-secret agent-memory-server --transport http --host 0.0.0.0
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 MCP Memory Server                   │
│  Transport: stdio | Streamable HTTP                 │
│                                                     │
│  ┌─── MCP Tools ───┐  ┌─── MCP Resources ────┐    │
│  │ store_memory     │  │ memory://stats        │    │
│  │ search_memory    │  │ memory://recent        │    │
│  │ update_memory    │  │ memory://namespaces    │    │
│  │ delete_memory    │  │ memory://consolidations │    │
│  │ list_memories    │  └────────────────────────┘    │
│  │ consolidate      │                                │
│  │ ingest_file/text │                                │
│  │ get_stats        │                                │
│  └──────────────────┘                                │
│                                                     │
│  ┌─── Processing Layer ───────────────────────┐     │
│  │ EmbeddingProvider (configurable)           │     │
│  │   OpenAI / Ollama / custom endpoint        │     │
│  │                                            │     │
│  │ ConsolidationEngine (configurable LLM)     │     │
│  │   OpenAI / Ollama / custom endpoint        │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  ┌─── Storage Layer ─────────────────────────┐     │
│  │ SQLite + sqlite-vec (vector search)       │     │
│  │ Automatic fallback to recency search      │     │
│  └────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

---

## Development

```bash
git clone https://github.com/khang/agent-memory.git
cd agent-memory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Run server locally
python -m agent_memory --config config.example.yaml
```

---

## License

MIT
