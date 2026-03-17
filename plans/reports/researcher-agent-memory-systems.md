# Research Report: Independent Agent Memory Systems

**Date:** 2026-03-16
**Sources:** 5 (GitHub repo analysis, Gemini research x2, direct code review)
**Key terms:** MCP memory server, agent memory layer, always-on memory, vector+graph hybrid, tool-based memory

---

## Executive Summary

Google's **always-on-memory-agent** demonstrates a clean, minimal architecture for persistent agent memory: SQLite storage, LLM-driven extraction/consolidation (no embeddings), and an HTTP API. It uses Google ADK with Gemini Flash-Lite for cost-effective 24/7 operation.

For your goal of building an **independent memory system exposing tools for any agent framework**, the optimal path is an **MCP server** backed by SQLite (local-first) or Postgres+pgvector (team/cloud), exposing `store`, `query`, `search`, `consolidate`, and `delete` tools. This makes memory framework-agnostic — Claude Code, Cursor, LangGraph, CrewAI all connect via MCP protocol.

---

## Key Findings

### 1. Google's Always-On Memory Agent — Deep Analysis

**Source:** [github.com/GoogleCloudPlatform/generative-ai/.../always-on-memory-agent](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/agents/always-on-memory-agent)

#### Architecture
Single-file (`agent.py`, 677 lines) multi-agent system using Google ADK:

```
                    ┌──────────────────┐
                    │   Orchestrator   │
                    │  (routes tasks)  │
                    └───┬────┬────┬────┘
                        │    │    │
              ┌─────────┘    │    └─────────┐
              ▼              ▼              ▼
        ┌───────────┐ ┌───────────┐ ┌───────────┐
        │  Ingest   │ │Consolidate│ │   Query   │
        │  Agent    │ │  Agent    │ │   Agent   │
        └───────────┘ └───────────┘ └───────────┘
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                    ┌──────────────────┐
                    │   SQLite DB      │
                    │   (memory.db)    │
                    └──────────────────┘
```

#### Database Schema (SQLite)

```sql
-- Raw memories with LLM-extracted metadata
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL,
    summary TEXT NOT NULL,
    entities TEXT NOT NULL DEFAULT '[]',    -- JSON array
    topics TEXT NOT NULL DEFAULT '[]',      -- JSON array
    connections TEXT NOT NULL DEFAULT '[]', -- JSON array of {linked_to, relationship}
    importance REAL NOT NULL DEFAULT 0.5,   -- 0.0 to 1.0
    created_at TEXT NOT NULL,
    consolidated INTEGER NOT NULL DEFAULT 0
);

-- Higher-level synthesized insights
CREATE TABLE consolidations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ids TEXT NOT NULL,    -- JSON array of memory IDs
    summary TEXT NOT NULL,
    insight TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Deduplication tracker for file ingestion
CREATE TABLE processed_files (
    path TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);
```

#### Key Design Decisions
- **No vector DB / No embeddings** — relies on Gemini's long context window + LLM-driven structuring
- **Retrieval = dump last 50 memories into context** — simple but limited to ~50 memories
- **Consolidation = brain's "sleep cycle"** — periodic LLM pass finds patterns, creates insights, links related memories
- **Multimodal ingestion** — supports 27 file types (text, images, audio, video, PDFs) via Gemini native multimodal

#### Tools Exposed (ADK function tools)
| Tool | Purpose | Args |
|------|---------|------|
| `store_memory` | Save extracted memory | raw_text, summary, entities, topics, importance, source |
| `read_all_memories` | Get last 50 memories | — |
| `read_unconsolidated_memories` | Get pending memories | — |
| `store_consolidation` | Save insight + connections | source_ids, summary, insight, connections |
| `read_consolidation_history` | Get last 10 insights | — |
| `get_memory_stats` | Counts | — |
| `delete_memory` | Remove by ID | memory_id |
| `clear_all_memories` | Full reset | inbox_path |

#### HTTP API
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Memory statistics |
| `/memories` | GET | List all memories |
| `/ingest` | POST | Ingest text `{"text": "...", "source": "..."}` |
| `/query?q=...` | GET | Query with natural language |
| `/consolidate` | POST | Trigger consolidation |
| `/delete` | POST | Delete memory `{"memory_id": 1}` |
| `/clear` | POST | Full reset |

#### Limitations
- **Scalability ceiling** — reads ALL 50 memories into context for every query (no semantic search)
- **No user/session scoping** — single flat namespace
- **No embedding-based retrieval** — won't find semantically similar memories when DB grows large
- **Tight coupling to Google ADK** — not framework-agnostic
- **No MCP interface** — only HTTP API

---

### 2. Agent Memory Landscape (2025-2026)

| Project | Architecture | Storage | Key Innovation | MCP Support |
|---------|-------------|---------|----------------|-------------|
| **Mem0** | Multi-level scopes (User/Session/Agent) | Qdrant/Pinecone + Graph | Personalization-first, auto-extraction | Yes |
| **Letta (MemGPT)** | OS-style tiered memory (Core/Recall/Archival) | Postgres + custom | Agent self-manages its own memory | Yes |
| **Zep** | Temporal knowledge graphs | Postgres + Graphiti | Tracks how facts change over time | Partial |
| **Cognee** | ECL pipeline (Extract/Cognify/Load) | LanceDB + Neo4j | Deterministic knowledge graph extraction | No |
| **LangMem** | LangGraph-native long-term memory | Relational + Vector | Long-term learning loops that optimize prompts | No |

#### Memory Type Taxonomy
1. **Episodic** — specific events/conversations ("Yesterday we discussed the API migration")
2. **Semantic** — general facts extracted from episodes ("Production API uses OAuth2")
3. **Procedural** — how-to knowledge from past feedback ("Always validate JSON before write_file")

---

### 3. MCP Memory Server Architecture (Recommended Approach)

The MCP protocol is the clear winner for framework-agnostic memory. Any MCP client (Claude Code, Cursor, Windsurf, custom agents) auto-discovers tools on connection.

#### Recommended Tool Schema

```json
{
  "tools": [
    {
      "name": "store_memory",
      "description": "Store a fact, preference, or knowledge item",
      "inputSchema": {
        "type": "object",
        "properties": {
          "content": { "type": "string" },
          "category": { "type": "string", "enum": ["fact", "preference", "procedure", "episode"] },
          "importance": { "type": "number", "minimum": 0, "maximum": 1 },
          "tags": { "type": "array", "items": { "type": "string" } },
          "scope": { "type": "string", "enum": ["global", "project", "session"] }
        },
        "required": ["content"]
      }
    },
    {
      "name": "search_memory",
      "description": "Semantic search across stored memories",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": { "type": "string" },
          "top_k": { "type": "number", "default": 10 },
          "category": { "type": "string" },
          "scope": { "type": "string" }
        },
        "required": ["query"]
      }
    },
    {
      "name": "update_memory",
      "description": "Update or correct an existing memory",
      "inputSchema": {
        "type": "object",
        "properties": {
          "memory_id": { "type": "string" },
          "content": { "type": "string" },
          "importance": { "type": "number" }
        },
        "required": ["memory_id"]
      }
    },
    {
      "name": "delete_memory",
      "description": "Remove a memory by ID",
      "inputSchema": {
        "type": "object",
        "properties": { "memory_id": { "type": "string" } },
        "required": ["memory_id"]
      }
    },
    {
      "name": "consolidate_memories",
      "description": "Trigger LLM-driven consolidation of recent memories into insights",
      "inputSchema": { "type": "object", "properties": {} }
    },
    {
      "name": "get_memory_stats",
      "description": "Get memory system statistics",
      "inputSchema": { "type": "object", "properties": {} }
    }
  ]
}
```

#### Recommended Architecture

```
┌─────────────────────────────────────────────────┐
│              MCP Memory Server                  │
│  (stdio or SSE transport)                       │
│                                                 │
│  Tools:                                         │
│    store_memory    search_memory                │
│    update_memory   delete_memory                │
│    consolidate     get_stats                    │
│                                                 │
│  ┌────────────────────────────────────────┐     │
│  │        Memory Processing Layer         │     │
│  │  - LLM extraction (entities, topics)   │     │
│  │  - Embedding generation                │     │
│  │  - Deduplication                       │     │
│  │  - Consolidation (periodic)            │     │
│  └────────────┬───────────────────────────┘     │
│               │                                 │
│  ┌────────────▼───────────────────────────┐     │
│  │        Storage Layer                   │     │
│  │  Option A: SQLite + sqlite-vec (local) │     │
│  │  Option B: Postgres + pgvector (cloud) │     │
│  └────────────────────────────────────────┘     │
└─────────────────────────────────────────────────┘
        ▲          ▲          ▲          ▲
        │          │          │          │
   Claude Code  Cursor    LangGraph   CrewAI
```

---

### 4. Storage Backend Comparison

| Backend | Best For | Pros | Cons |
|---------|----------|------|------|
| **SQLite + sqlite-vec** | Local CLI tools, single-user | Zero config, fast, portable, private | Single-writer, no remote access |
| **Postgres + pgvector** | Teams, cloud, multi-agent | Scalable, ACID, remote, concurrent | Requires server setup |
| **Hybrid (relational + vector)** | Complex agents with both structured and semantic data | Best of both worlds | More complexity |

**Recommendation:** Start with **SQLite + sqlite-vec** for local-first, then add Postgres adapter for cloud/team scenarios. Use adapter pattern so storage is swappable.

---

### 5. Implementation Skeleton (Python MCP Server)

```python
from mcp.server.fastmcp import FastMCP
import sqlite3
import json

mcp = FastMCP("agent-memory")

@mcp.tool()
async def store_memory(content: str, category: str = "fact",
                       importance: float = 0.5, tags: list[str] = [],
                       scope: str = "global") -> str:
    """Store a memory with metadata extraction."""
    # 1. Generate embedding via local model or API
    # 2. LLM-extract entities/topics (optional, can be deferred)
    # 3. Insert into DB with vector
    # 4. Return confirmation
    pass

@mcp.tool()
async def search_memory(query: str, top_k: int = 10,
                        category: str = None, scope: str = None) -> list[dict]:
    """Semantic search across memories."""
    # 1. Embed query
    # 2. Vector similarity search
    # 3. Optional: re-rank with metadata filters
    # 4. Return results
    pass

@mcp.tool()
async def consolidate_memories() -> str:
    """LLM-driven consolidation of recent unconsolidated memories."""
    # 1. Read unconsolidated memories
    # 2. Ask LLM to find patterns, deduplicate, create insights
    # 3. Store consolidation record
    # 4. Mark memories as consolidated
    pass
```

---

### 6. Key Insights from Google's Approach vs. Industry

| Aspect | Google AOMA | Industry Best Practice (2026) |
|--------|------------|-------------------------------|
| **Retrieval** | Dump last 50 into context | Vector similarity search (scales to millions) |
| **Storage** | SQLite, no vectors | SQLite-vec / pgvector for semantic retrieval |
| **Consolidation** | LLM periodic pass | Same, but with dedup + importance decay |
| **Interface** | HTTP REST API | MCP server (framework-agnostic) |
| **Scoping** | Single flat namespace | User / Project / Session scopes |
| **Embeddings** | None | Local embeddings (nomic-embed, all-MiniLM) |

Google's approach is intentionally simple — good for demo/prototype. For production, add vector search and MCP interface.

---

## Implementation Recommendations

### Quick Start Path
1. **Fork Google's always-on-memory-agent** as reference architecture
2. **Replace HTTP API with MCP server** using `mcp.server.fastmcp`
3. **Add sqlite-vec** for semantic search (replaces "dump all 50" retrieval)
4. **Add scoping** (user_id, project_id, session_id) to memory schema
5. **Keep consolidation loop** — it's the most novel part of Google's design
6. **Add embedding generation** — use local model (nomic-embed-text) or API

### Architecture Decisions
- **Transport:** stdio for local (Claude Code), SSE for remote (web agents)
- **Embedding model:** nomic-embed-text (local, free) or OpenAI text-embedding-3-small
- **LLM for consolidation:** Any cheap model (Gemini Flash, Claude Haiku, GPT-4o-mini)
- **Config:** ENV vars for DB path, embedding model, consolidation interval

### Schema Evolution from AOMA
```sql
-- Enhanced schema with vector search + scoping
CREATE TABLE memories (
    id TEXT PRIMARY KEY,              -- UUID instead of autoincrement
    user_id TEXT DEFAULT 'default',   -- Multi-user support
    project_id TEXT DEFAULT 'global', -- Project scoping
    content TEXT NOT NULL,
    summary TEXT,
    entities TEXT DEFAULT '[]',
    topics TEXT DEFAULT '[]',
    category TEXT DEFAULT 'fact',     -- fact/preference/procedure/episode
    importance REAL DEFAULT 0.5,
    embedding BLOB,                   -- Vector for similarity search
    connections TEXT DEFAULT '[]',
    consolidated INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE consolidations (
    id TEXT PRIMARY KEY,
    source_ids TEXT NOT NULL,
    summary TEXT NOT NULL,
    insight TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

---

## Resources & References

### Primary Sources
- [Google Always-On Memory Agent](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/agents/always-on-memory-agent) — Reference implementation analyzed
- [Google ADK (Agent Development Kit)](https://google.github.io/adk-docs/) — Agent framework used
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — For building MCP servers

### Memory Systems
- [Mem0](https://github.com/mem0ai/mem0) — Personalized memory with MCP support
- [Letta (MemGPT)](https://www.letta.com/) — OS-style agent memory management
- [Zep / Graphiti](https://github.com/getzep/graphiti) — Temporal knowledge graphs
- [Cognee](https://www.cognee.ai/) — Deterministic knowledge graph extraction

### Storage
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — Vector search extension for SQLite
- [pgvector](https://github.com/pgvector/pgvector) — Vector similarity for Postgres

---

## Unresolved Questions

1. ~~**Embedding model choice**~~ → RESOLVED: Configurable provider endpoint + API key, also support local LLM runtimes (Ollama)
2. ~~**Consolidation LLM**~~ → RESOLVED: External/configurable — server stays independent, grows with model capability, user-choice
3. **Conflict resolution:** When two agents store contradictory facts, which wins? Timestamp-based? Importance-based? Ask user?
4. **Memory decay:** Should old, unconsolidated, low-importance memories be auto-pruned?
5. ~~**Multi-transport**~~ → RESOLVED: stdio + Streamable HTTP

---

## Validation Log

### Session 1 — 2026-03-16
**Trigger:** Pre-plan validation of research findings
**Questions asked:** 8

#### Questions & Answers

1. **[Architecture]** What programming language should the MCP memory server be built in?
   - Options: Python (Recommended) | TypeScript | Both
   - **Answer:** Python
   - **Rationale:** FastMCP SDK, matches reference impl, rich ecosystem

2. **[Architecture]** What storage backend should we start with?
   - Options: SQLite + sqlite-vec | Postgres + pgvector | Pluggable (adapter pattern)
   - **Answer:** Pluggable (adapter pattern)
   - **Rationale:** Abstract storage interface from day 1. Implement SQLite first, add Postgres later.

3. **[Architecture]** How should embedding generation work?
   - Options: Local model | API-based | Configurable | No embeddings
   - **Answer:** Configurable provider endpoint + API key, also support local LLM runtimes (Ollama)
   - **Rationale:** User provides provider endpoint + API. Also support local runtimes like Ollama. Maximum flexibility.

4. **[Architecture]** Should consolidation engine be built-in or external?
   - Options: Built-in | External trigger only | Hybrid
   - **Answer:** External/configurable — keep MCP independent
   - **Rationale:** Server stays independent and less outdated. Grows with model capability. User-choice option.

5. **[Scope]** What memory scoping model?
   - Options: User+Project+Session | Namespace-based | Single namespace
   - **Answer:** Namespace-based
   - **Rationale:** Flat namespaces like 'user:khang', 'project:agent-memory'. User defines taxonomy.

6. **[Architecture]** What MCP transport modes?
   - Options: stdio | SSE | Streamable HTTP
   - **Answer:** stdio + Streamable HTTP
   - **Rationale:** stdio for local CLI tools, Streamable HTTP for remote/cloud agents.

7. **[Scope]** What's the target MVP scope?
   - Options: Core tools only | Core + consolidation | Full feature set
   - **Answer:** Full feature set
   - **Rationale:** Core + consolidation + file ingestion + multimodal + dashboard. Matches Google reference.

8. **[Architecture]** Should memory server support MCP Resources?
   - Options: Tools only | Tools + Resources
   - **Answer:** All — Tools + Resources + Agent Skill
   - **Custom input:** Also create an agent skill (via skill-creator standard) so agents know how to use the MCP properly, not try-and-fail.
   - **Rationale:** Full MCP interface with an accompanying skill that teaches agents how to use the memory system.

#### Confirmed Decisions
- **Language:** Python with FastMCP SDK
- **Storage:** Pluggable adapter pattern, SQLite first
- **Embeddings:** Configurable provider (API endpoint + key), support Ollama/local
- **Consolidation:** External/configurable LLM, server stays model-agnostic
- **Scoping:** Namespace-based flat taxonomy
- **Transport:** stdio + Streamable HTTP
- **MVP Scope:** Full feature set (memory tools + consolidation + ingestion + dashboard)
- **MCP Interface:** Tools + Resources + Agent Skill (skill-creator standard)

#### Action Items
- [ ] Create implementation plan with all phases
- [ ] Design pluggable storage adapter interface
- [ ] Design configurable embedding provider interface
- [ ] Design configurable LLM provider for consolidation
- [ ] Create agent skill using skill-creator standard
- [ ] Plan dashboard (Streamlit or alternative)
