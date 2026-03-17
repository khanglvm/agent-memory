# Project Overview & Product Development Requirements

## Project Identity

**Name:** agent-memory (agent-memory-server)
**Version:** 0.1.0
**Status:** MVP Complete (March 2026)
**License:** MIT
**Repository:** https://github.com/khanglvm/agent-memory

## Vision

Enable AI agents to maintain persistent, searchable knowledge across sessions without vendor lock-in. Provide a framework-agnostic memory system that integrates seamlessly with any MCP-compatible client while remaining simple to self-host and configure.

## Target Users

1. **AI Agent Developers** — Building agents in LangGraph, CrewAI, or other frameworks
2. **MCP Client Users** — Claude Code, Cursor, Windsurf, Cline users wanting memory
3. **System Integrators** — Teams deploying multi-agent systems needing shared memory
4. **Privacy-Conscious Enterprises** — Organizations wanting self-hosted memory without cloud dependencies

## Key Features

### Core (MVP Complete)
- **Memory Storage** — Persistent storage of facts, preferences, procedures, episodes
- **Semantic Search** — Vector-based similarity search with embedding providers (OpenAI, Ollama)
- **Namespace Isolation** — Multi-tenant scoping (global, project, user-level namespaces)
- **Consolidation** — LLM-driven pattern detection, deduplication, insight generation
- **File Ingestion** — Import text and structured files as memories
- **MCP Protocol** — 9 tools + 4 resources via stdio or HTTP
- **Configurable Providers** — Pluggable embeddings and LLMs
- **Zero-Config Default** — Works immediately with SQLite + recency search

### Non-Functional
- **Security** — Bearer token auth, prompt injection defense (XML/CDATA wrapping), symlink resolution
- **Reliability** — Atomic writes, circuit breaker for consolidation, async/await throughout
- **Testability** — 109 unit tests, 95%+ coverage, pytest + respx for HTTP mocking
- **Portability** — Python 3.11+, single-file deployments via uvx, Docker-ready

## Success Metrics

### Adoption
- Installation via PyPI (target: 500+ downloads in first month)
- GitHub stars (target: 100+)
- Community contributions (target: 2+ external PRs)

### Product Quality
- 100+ passing tests (achieved: 109)
- 0 high-severity security findings (achieved: 15 red team findings resolved)
- <50ms latency for store/search operations
- 99%+ uptime in self-hosted deployments

### User Experience
- <5 min setup time (zero-config default)
- Works with 4+ client frameworks (Claude Code, Cursor, Windsurf, Cline verified)
- Comprehensive docs with examples for each use case

## Architecture Principles

**Simplicity First:** Single SQLite file, no external services required by default.

**Pluggable:** Swap embedding providers (OpenAI → Ollama → None) without code changes.

**Graceful Degradation:** Without embeddings, system falls back to recency search.

**Secure by Default:** Bearer tokens, allowlist file paths, circuit breaker for external LLM calls.

**Developer-Friendly:** Clear API, detailed error messages, observability via logging.

## Technical Constraints

- **Python 3.11+** — Leverages match statements, type hints, async improvements
- **SQLite** — No external database; sqlite-vec for vectors when available
- **MCP Protocol** — Locked to v1.0+; ensures compatibility with MCP ecosystem
- **Async/Await** — Non-blocking I/O throughout; required for MCP streaming
- **API Keys Optional** — Embedding and consolidation are optional; system works without them

## Dependencies

### Core
- mcp[cli]>=1.0.0 — MCP protocol implementation
- pydantic>=2.0 — Data validation
- pyyaml>=6.0 — Configuration parsing
- sqlite-vec>=0.1.0 — Vector search in SQLite
- aiosqlite>=0.20.0 — Async SQLite driver
- httpx>=0.27.0 — Async HTTP client
- uvicorn>=0.30.0 — ASGI server for HTTP transport

### Dev
- pytest, pytest-asyncio, pytest-cov — Testing
- respx — HTTP mocking
- ruff — Linting and formatting

## Functional Requirements

### FR-1: Memory Operations
- Store memories with content, optional summary, entities, topics, category, importance
- Search memories by semantic similarity (with embeddings) or recency (fallback)
- Update memories in-place with new content/metadata
- Delete memories atomically
- List memories by namespace with pagination

### FR-2: Consolidation
- Trigger consolidation manually or on schedule (configurable interval)
- LLM analyzes memory clusters to extract patterns and insights
- Deduplicates overlapping memories
- Marks consolidated memories for later cleanup
- Results stored as Consolidation records with source IDs

### FR-3: Ingestion
- Import plain text or structured files (JSON, CSV, YAML, XML, Markdown, Log)
- LLM enrichment optional (extract entities, topics, summary)
- Path allowlist validation (disable by default for security)
- File size limits configurable (default: 1 MB)

### FR-4: Namespace Management
- Create/list namespaces
- Per-namespace memory isolation
- Per-namespace consolidation jobs

### FR-5: MCP Interface
- 9 tools (store, search, update, delete, list, stats, consolidate, ingest_text, ingest_file)
- 4 resources (stats, recent, namespaces, consolidations)
- Graceful error handling with MCP ErrorSchema

### FR-6: Configuration
- YAML-based configuration with env var overrides
- Multiple embedding providers (OpenAI, Ollama, None)
- Multiple LLM providers for consolidation
- Storage location, ingestion paths, feature flags all configurable

## Non-Functional Requirements

### NFR-1: Security
- Bearer token authentication for HTTP transport
- Prompt injection defense via XML/CDATA wrapping in consolidation
- Path traversal prevention via symlink resolution
- SQL injection prevention via parameterized queries
- Circuit breaker prevents cascading LLM failures

### NFR-2: Performance
- Vector search <50ms for typical queries
- Memory store operations <100ms
- Consolidation background task non-blocking

### NFR-3: Reliability
- Atomic database writes (WAL mode SQLite)
- Graceful shutdown handling (SIGTERM/SIGINT)
- Circuit breaker for external LLM calls (3 retry threshold)
- Automatic schema initialization

### NFR-4: Observability
- Structured logging with log levels (DEBUG, INFO, WARN, ERROR)
- Tool input/output logged for debugging
- Error traces preserved

## Out of Scope (Post-MVP)

- **Multimodal Ingestion** — Image/audio processing
- **File Watching** — Auto-ingest changes to monitored directories
- **Web Dashboard** — UI for memory exploration (CLI/API sufficient)
- **PostgreSQL Adapter** — SQLite default; other DBs as community contributions
- **Dual Transport** — Run stdio and HTTP simultaneously
- **Multi-Agent Collaboration** — Shared memory coordination protocols

## Risk Assessment

### Risk: Vector Search Failures
**Impact:** Fallback to recency search (lower relevance)
**Mitigation:** Noop provider + fallback search already implemented

### Risk: LLM Consolidation Costs
**Impact:** API fees, slow consolidation, cascading failures
**Mitigation:** Circuit breaker, configurable interval, optional feature

### Risk: Adoption — Vendor Lock-In Concerns
**Impact:** Users hesitant to adopt due to SQLite dependency
**Mitigation:** Emphasize self-hosting, clear export mechanisms in post-MVP

### Risk: Security — Prompt Injection
**Impact:** LLM consolidation could be manipulated via malicious memories
**Mitigation:** XML/CDATA wrapping tested against red team scenarios

## Success Criteria

### MVP Complete (2026-03-16) ✓
- 9 MCP tools functional
- SQLite storage with vector search
- Configurable embedding and LLM providers
- 109 tests passing
- 0 high-severity security issues
- Comprehensive documentation

### Phase 2 (Post-MVP)
- PostgreSQL adapter
- File watcher for continuous ingestion
- Web UI for memory exploration
- Metrics/monitoring dashboard

## Stakeholder Alignment

**Internal:** Framework-agnostic design appeals to Python ecosystem broadly
**External:** MCP standardization enables vendor interoperability
**Community:** Open source with MIT license attracts contributions

## Success Definition

Agent-memory succeeds when:
1. 500+ developers use it monthly
2. Works seamlessly with 5+ agent frameworks
3. Zero critical security incidents in production
4. Sub-50ms vector search performance maintained at scale
5. Community maintains 20%+ of non-critical PRs
