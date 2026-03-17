# Project Roadmap

Status, current focus, and future direction for agent-memory.

## Current Status

**Version:** 0.1.0 (MVP Complete)
**Release Date:** March 16, 2026
**Development Time:** ~38 hours
**Test Coverage:** 109 tests passing, 95%+ coverage

### What's Complete

- **Core Memory Operations** (store, search, update, delete, list)
- **Vector Search** (with sqlite-vec, OpenAI/Ollama embedding providers)
- **Consolidation Engine** (LLM-driven pattern detection, deduplication)
- **File Ingestion** (text/structured files with optional enrichment)
- **MCP Protocol** (9 tools + 4 resources, stdio transport)
- **HTTP Transport** (Streamable, bearer token auth)
- **Configuration** (YAML + env var overrides)
- **Security** (prompt injection defense, path validation, SQL prevention)
- **Testing** (100+ tests, async fixtures, HTTP mocking)
- **Documentation** (README, deployment guide, code standards)

### Known Limitations

- **Single-Host Only** — No distributed memory across agents
- **SQLite Backend Only** — PostgreSQL deferred
- **Manual Consolidation** — Auto-scheduling implemented but not exposed in UI
- **File Ingestion Limited** — Single-file only, no directory watching
- **No Dashboard** — CLI/API sufficient for MVP
- **Vector Dimensions Fixed** — Cannot migrate between embedding models easily

## Phase 1: Stabilization & Early Adoption (April-May 2026)

**Priority:** High
**Goal:** 500+ monthly users, community adoption

### Initiatives

1. **Community Feedback Loop** (Week 1-2)
   - Publish on HN/Reddit
   - Gather usage patterns
   - Document common configurations

2. **Performance Profiling** (Week 2-3)
   - Benchmark search latency at scale (10K memories)
   - Optimize hot paths
   - Target: <50ms vector search maintained

3. **Reliability Hardening** (Week 3-4)
   - Deploy to production use cases
   - Monitor error rates
   - Fix edge cases (large consolidations, memory limits)

### Deliverables

- Public website / documentation site
- Deployment templates (Docker, systemd, K8s)
- FAQ based on early user feedback
- Performance benchmarks published

### Success Criteria

- 500+ PyPI downloads
- 50+ GitHub stars
- 0 critical bugs post-release
- Sub-100ms 95th percentile search latency

---

## Phase 2: PostgreSQL & Scalability (June-July 2026)

**Priority:** High
**Goal:** Enterprise-ready, multi-tenant support

### Initiatives

1. **PostgreSQL Adapter** (Week 1-3)
   - Drop-in replacement for SQLiteStorage
   - Same interface, different backend
   - Connection pooling via asyncpg
   - Support for pgvector extension (open source)

2. **Scaling Testing** (Week 3-4)
   - 100K+ memories per namespace
   - Concurrent consolidation jobs
   - Load testing with realistic workloads

### Features

```python
# Drop-in replacement
if config.storage.backend == "postgres":
    storage = PostgresStorage(config)
else:
    storage = SQLiteStorage(config)
```

### Deliverables

- PostgreSQL storage implementation
- Migration guide (SQLite → Postgres)
- Performance comparison (SQLite vs Postgres)
- Multi-tenant examples

### Success Criteria

- 100K memories searchable in <100ms
- Concurrent consolidation jobs (no locking issues)
- 0 data loss in failover scenarios

---

## Phase 3: Continuous Ingestion (August 2026)

**Priority:** Medium
**Goal:** Auto-monitor and ingest files, enable knowledge synchronization

### Initiatives

1. **File Watcher** (Week 1-2)
   - Watch allowed directories
   - Auto-ingest on file changes
   - Debounce rapid changes

2. **Scheduled Consolidation** (Week 2-3)
   - UI/CLI for auto-consolidation schedules
   - Publish consolidation results
   - Configurable auto-cleanup of old memories

### Features

```yaml
ingestion:
  watch_paths:
    - ~/projects
    - /data/docs
  auto_consolidate:
    enabled: true
    interval_minutes: 60
    min_memories: 5
```

### Deliverables

- File watcher implementation (watchdog integration)
- Scheduler for consolidation (APScheduler)
- Metrics for ingestion activity
- Example: Project documentation auto-import

### Success Criteria

- Watch 100K+ files without performance impact
- Auto-consolidation runs reliably on schedule
- <5min latency from file change to memory availability

---

## Phase 4: Web Dashboard (September-October 2026)

**Priority:** Medium
**Goal:** Visualize memory, simplify configuration

### Initiatives

1. **Memory Explorer** (Week 1-3)
   - List/search memories by namespace
   - View memory details (embeddings, topics, entities)
   - Edit/delete UI
   - Search by similarity with interactive testing

2. **Configuration UI** (Week 3-4)
   - Visual config builder (no YAML editing)
   - Test embedding/LLM providers
   - Monitor consolidation jobs

3. **Metrics Dashboard** (Week 4)
   - Memory count trends
   - Search latency distribution
   - Consolidation success rate
   - Storage usage

### Tech Stack

- **Frontend:** React + Tailwind (or simple HTML + htmx)
- **Backend:** FastAPI (existing MCP server)
- **Hosting:** Single binary via uvicorn

### Deliverables

- Standalone web dashboard
- Docker image with dashboard included
- Mobile-responsive UI

### Success Criteria

- <3s page load time
- 10+ concurrent users without slowdown
- Simplified onboarding for new users

---

## Phase 5: Distributed Memory (2027+)

**Priority:** Low (post-MVP, community-driven)
**Goal:** Share memory across multiple agents, real-time synchronization

### Concepts

1. **Memory Sync Protocol**
   - Agent-to-agent communication
   - Conflict resolution (LLM-driven merging)
   - Distributed consolidation

2. **Shared Namespaces**
   - Central memory hub
   - Federated agents (each has local cache)
   - Partial sync (relevant memories only)

3. **Access Control**
   - Memory sharing policies (read/write/consolidate)
   - Role-based access (agent, team, organization)
   - Audit logs

### Research Questions

- How to prevent duplicate consolidations?
- What's the minimal sync set for each agent?
- How to handle conflict resolution?
- Performance of sync over high-latency networks?

### Deliverables

- Proof-of-concept sync protocol
- Conflict resolution LLM prompts
- Performance benchmarks

---

## Deferred / Community-Driven

### Multimodal Ingestion
- Image ingestion (OCR + vision embedding)
- Audio transcription + storage
- Video processing (keyframes + transcription)

**Status:** Deferred (requires vision APIs, complexity)
**Owner:** Community contribution

### Export / Backup
- Memory export to JSON/CSV
- Bulk backup/restore
- Data portability

**Status:** Post-MVP
**Owner:** Community contribution

### Vector Migration
- Tool to switch embedding providers
- Batch re-embed memories
- Zero-downtime migration

**Status:** Post-MVP
**Owner:** Community contribution

### Local LLM Fine-Tuning
- Fine-tune Ollama on consolidated insights
- Improve consolidation quality over time
- Private knowledge model

**Status:** Research phase
**Owner:** Research spike

### Memory Compression
- Summarize old memories
- Archive less-relevant data
- Reduce storage over time

**Status:** Research phase
**Owner:** Community contribution

---

## Timeline Overview

```
                   Q2 2026              Q3 2026             Q4 2026        2027+
                   ┌─────────┐         ┌────────┐          ┌──────┐        ┌────┐
Phase Roadmap:     │Phase 1  │ ─────→ │Phase 2 │ ────────→│Phase│ ────→ │Phase
                   │Stabiliz │        │Postgres│         │3    │        │5
                   └─────────┘        │Scaling │         └──────┘        │Distrib
                                       └────────┘                         └────┘
                                              │
                    (Parallel)               Phase 4
                    Community              Web Dashboard
                    Contributions           + Metrics
                    (Multimodal,
                     Migrations,
                     Export)
```

## Success Metrics by Phase

### Phase 1 (April-May)
- 500+ PyPI downloads
- 50+ GitHub stars
- 3+ production deployments
- <1% bug report rate

### Phase 2 (June-July)
- 2K+ monthly downloads
- 200+ GitHub stars
- 5+ enterprise users
- PostgreSQL feature parity

### Phase 3 (August)
- 5K+ monthly downloads
- 500+ GitHub stars
- File watching in 80% of deployments
- Auto-consolidation reliability >99%

### Phase 4 (Sept-Oct)
- 10K+ monthly downloads
- 1K+ GitHub stars
- Dashboard adoption >40% of users
- Simplified onboarding (sub-5min setup)

### Phase 5 (2027+)
- Multi-agent deployments
- Distributed memory production use cases
- Research publications

---

## Stretch Goals

### Q2 2026
- Language-specific SDKs (JavaScript, Go, Rust)
- Integration with LangChain, LlamaIndex

### Q3 2026
- Kubernetes Helm chart
- Performance benchmarks: 1M memories <100ms search
- 99.9% uptime SLA

### Q4 2026
- Mobile companion app (view recent memories)
- Slack integration (memory lookups via slash commands)

### 2027
- Agent marketplace (pre-configured memory systems)
- Research paper on LLM-driven memory consolidation
- Enterprise support (SLA, dedicated support)

---

## Investment Areas

### Developer Experience
- Better error messages
- Interactive tutorials
- VS Code extension (memory browser)

### Security
- Key rotation mechanisms
- Encryption at rest (post-MVP)
- GDPR compliance (data deletion)

### Performance
- Horizontal scaling (sharding by namespace)
- Caching layer (Redis integration, post-MVP)
- Batch ingestion API

### Community
- Monthly blog posts
- Community demo day (quarterly)
- Bounty program for features

---

## How to Contribute

### Want to Help?

**Priority contributions:**
1. PostgreSQL adapter implementation
2. Performance benchmarks and profiling
3. Dashboard frontend (React/Vue/Svelte)
4. Kubernetes/Docker deployment
5. Documentation translations
6. Bug reports + fixes

**Process:**
1. Open GitHub issue with proposal
2. Wait for feedback from maintainers
3. Submit PR with tests
4. Code review cycle
5. Merge and release

**Contact:** Open discussion in GitHub Issues
