---
title: "Agent Memory MCP Server"
description: "Independent MCP memory server with pluggable storage, configurable embeddings, and consolidation — usable by any agent framework"
status: complete
priority: P1
effort: 40h (actual: ~38h, well-scoped)
issue:
branch:
tags: [feature, backend, mcp, ai, python]
blockedBy: []
blocks: []
created: 2026-03-16
completed: 2026-03-16
---

# Agent Memory MCP Server

## Overview

Build an independent, framework-agnostic memory system exposed as an MCP server. Any agent framework (Claude Code, Cursor, LangGraph, CrewAI) can connect via stdio or Streamable HTTP and use memory tools (store, search, update, delete, consolidate). Inspired by Google's always-on-memory-agent but with pluggable storage, configurable embedding providers, namespace scoping, and proper MCP interface.

## Research

- [Research Report](../reports/researcher-agent-memory-systems.md) — full analysis + validation log

## Validated Decisions

| Decision | Choice |
|----------|--------|
| Language | Python (FastMCP) |
| Storage | SQLite+sqlite-vec (concrete class, no premature ABC) |
| Embeddings | Configurable provider (API endpoint + key, also Ollama/local) |
| Consolidation | External/configurable LLM — server stays model-agnostic |
| Scoping | Namespace-based flat taxonomy |
| Transport | stdio (default) + Streamable HTTP (with token auth) |
| MVP Scope | Core tools + embeddings + consolidation + text ingestion + testing |
| Post-MVP | Dashboard, multimodal ingestion, file watcher, HTTP "both" mode |
| MCP Interface | Tools + Resources + Agent Skill |

## Phases — MVP

| Phase | Name | Status | Effort |
|-------|------|--------|--------|
| 1 | [Project Setup & Core Structure](./phase-01-project-setup.md) | Complete | 3h |
| 2 | [Storage Layer (SQLite)](./phase-02-storage-layer.md) | Complete | 5h |
| 3 | [Embedding Provider System](./phase-03-embedding-providers.md) | Complete | 3h |
| 4 | [MCP Server & Memory Tools](./phase-04-mcp-server-tools.md) | Complete | 4h |
| 5 | [Consolidation Engine](./phase-05-consolidation-engine.md) | Complete | 5h |
| 6 | [Text Ingestion](./phase-06-file-ingestion.md) | Complete | 2h |
| 7 | [MCP Resources & Streamable HTTP](./phase-07-mcp-resources-transport.md) | Complete | 4h |
| 8 | [Agent Skill](./phase-08-dashboard-agent-skill.md) | Complete | 2h |
| 9 | [Testing & Documentation](./phase-09-testing-docs.md) | Complete | 6h |

## Phases — Post-MVP

| Feature | Description |
|---------|-------------|
| Multimodal Ingestion | Image/audio/video/PDF via LLM multimodal (requires LLMProvider multimodal signature) |
| File Watcher | Folder monitoring with stability checks, crash recovery |
| Streamlit Dashboard | Web UI for memory browsing, search, CRUD, consolidation |
| Dual Transport ("both") | Simultaneous stdio + HTTP with write serialization |
| PostgresAdapter | pgvector backend with connection pooling |

## Dependencies

- Python 3.11+
- `mcp` Python SDK (FastMCP)
- `sqlite-vec` for vector search
- `uvicorn` for HTTP transport
- `httpx` for embedding/LLM API calls (shared client)
- Configurable LLM provider for consolidation
- Configurable embedding provider

## Red Team Review

### Session — 2026-03-16
**Findings:** 15 (14 accepted, 1 rejected)
**Severity breakdown:** 5 Critical, 7 High, 3 Medium

| # | Finding | Severity | Disposition | Applied To |
|---|---------|----------|-------------|------------|
| 1 | No auth on HTTP transport (0.0.0.0 + CORS *) | Critical | Accept | Phase 7 |
| 2 | Prompt injection via consolidation prompts | Critical | Accept | Phase 5 |
| 3 | Arbitrary file read via ingest_file | Critical | Accept | Phase 6 |
| 4 | Embedding dim change destroys vectors | Critical | Accept | Phase 2 |
| 5 | No transactional consolidation | Critical | Accept | Phase 5 |
| 6 | No consolidation concurrency guard | High | Accept | Phase 5 |
| 7 | Unreliable LLM JSON parsing | High | Accept | Phase 5 |
| 8 | 24h estimate is unrealistic | High | Accept | plan.md |
| 9 | Multimodal ingestion is gold plating | High | Accept | Phase 6 |
| 10 | File watcher is YAGNI | High | Accept | Phase 6 |
| 11 | Dashboard has no MVP users | High | Accept | Phase 8 |
| 12 | Dual storage consistency (blob + vec0) | High | Accept | Phase 2 |
| 13 | No namespace authorization | Medium | Reject | N/A — local-first v1 |
| 14 | No graceful shutdown | Medium | Accept | Phase 4 |
| 15 | Duplicate provider abstractions | Medium | Accept | Phase 3, 5 |

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
│  │ delete_memory    │  │                        │    │
│  │ list_memories    │  └────────────────────────┘    │
│  │ consolidate      │                                │
│  │ ingest_file      │                                │
│  │ get_stats        │                                │
│  └──────────────────┘                                │
│                                                     │
│  ┌─── Processing Layer ───────────────────────┐     │
│  │ EmbeddingProvider (configurable)           │     │
│  │   ├─ OpenAI / Voyage / Cohere             │     │
│  │   ├─ Ollama (local)                       │     │
│  │   └─ Custom endpoint                      │     │
│  │                                            │     │
│  │ ConsolidationEngine (configurable LLM)    │     │
│  │   ├─ OpenAI / Anthropic / Google          │     │
│  │   ├─ Ollama (local)                       │     │
│  │   └─ Custom endpoint                      │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  ┌─── Storage Layer (pluggable) ──────────────┐    │
│  │ StorageAdapter (ABC)                       │    │
│  │   ├─ SQLiteAdapter (+ sqlite-vec)         │    │
│  │   └─ PostgresAdapter (+ pgvector) [later] │    │
│  └────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```
