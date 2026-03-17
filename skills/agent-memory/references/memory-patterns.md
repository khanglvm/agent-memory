# Memory Patterns Reference

Detailed examples and workflows for the agent-memory MCP server.

---

## Core Tool Examples

### Storing Memories

**User preference (high importance):**
```python
store_memory(
  content="User prefers TypeScript over JavaScript. Always use strict mode.",
  namespace="user:alice",
  category="preference",
  importance=0.8,
  tags=["typescript", "language"]
)
```

**Project architecture decision:**
```python
store_memory(
  content="Database: PostgreSQL with pgvector. ORM: SQLAlchemy async. No raw SQL except migrations.",
  namespace="project:myapp",
  category="fact",
  importance=0.9,
  tags=["database", "architecture"]
)
```

**Resolved error (procedure):**
```python
store_memory(
  content="Fix for 'relation does not exist': run `alembic upgrade head` before starting server. Migrations must be applied manually in dev.",
  namespace="project:myapp",
  category="procedure",
  importance=0.7,
  tags=["alembic", "database", "error"]
)
```

**Session episode:**
```python
store_memory(
  content="Implemented JWT auth with refresh tokens. Decided against session cookies due to SPA architecture. Access token TTL: 15min, refresh: 7days.",
  namespace="project:myapp",
  category="episode",
  importance=0.6,
  tags=["auth", "jwt", "session-summary"]
)
```

---

### Searching Memories

**Before starting a task:**
```python
# Retrieve project context before touching auth code
results = search_memory(
  query="authentication and authorization setup",
  namespace="project:myapp",
  top_k=5
)
```

**User-specific context:**
```python
# Retrieve user preferences before generating code
results = search_memory(
  query="coding preferences and style",
  namespace="user:alice",
  top_k=3,
  category="preference"
)
```

**Cross-project search (global namespace):**
```python
# Find general patterns known from all projects
results = search_memory(
  query="common deployment patterns kubernetes",
  namespace="global",
  top_k=5
)
```

**Similarity threshold guidance:** Results include a `similarity` float (0–1). Treat results with similarity < 0.3 as weak matches; verify before relying on them.

---

### Updating Memories

Update when a fact changes — do NOT store a new memory for the same thing:

```python
# Old: "API deployed at api.staging.example.com"
# New URL after migration:
update_memory(
  memory_id="3f2a1b4c-...",
  content="API deployed at api.example.com (migrated from staging domain on 2026-03-15)",
  importance=0.8
)
```

Bump importance when a background fact becomes critical:
```python
update_memory(
  memory_id="3f2a1b4c-...",
  importance=0.9  # content unchanged, just escalating priority
)
```

---

### Consolidation

After a session with many stores, consolidation extracts cross-memory patterns:

```python
# Check if consolidation is worthwhile
stats = get_memory_stats(namespace="project:myapp")
# stats.unconsolidated_count >= 5 → consolidate

result = consolidate_memories(namespace="project:myapp")
# Returns: summary, insight, source_ids
# Insight example: "3 memories relate to auth failures — consider a dedicated auth-error procedure"
```

Read consolidation results via resource:
```
memory://consolidations/project:myapp
```

---

### Ingesting Long Content

For documents, meeting notes, or large text blocks — do NOT store as a single memory:

```python
# Ingest a design doc
ingest_text(
  text="<full text of RFC or design doc>",
  source="auth-rfc-v2",
  namespace="project:myapp"
)

# Ingest a local file
ingest_file(
  file_path="/Users/alice/projects/myapp/docs/architecture.md",
  namespace="project:myapp"
)
```

The server chunks automatically and creates multiple memories from the content.

---

## Common Workflows

### Onboarding a New User

Goal: capture preferences and context at the start of a relationship.

```
1. Ask about preferences (language, style, workflow)
2. store_memory each preference: category="preference", namespace="user:{name}", importance=0.7+
3. Ask about current projects
4. store_memory project context: category="fact", namespace="project:{name}", importance=0.8
5. Session end → search_memory to verify context captured correctly
```

### Starting Work on a Known Project

```
1. search_memory(query="project overview and tech stack", namespace="project:{name}", top_k=5)
2. search_memory(query="recent decisions and changes", namespace="project:{name}", top_k=3, category="episode")
3. Check memory://recent/project:{name} for latest activity
4. Proceed with task using retrieved context
```

### End-of-Session Wrap-Up

```
1. store_memory(
     content="<summary of what was done, decisions made, open questions>",
     namespace="project:{name}",
     category="episode",
     importance=0.6,
     tags=["session-summary", "<date>"]
   )
2. If 5+ memories added this session: consolidate_memories(namespace="project:{name}")
3. Store any user feedback or corrections observed during session
```

### Tracking User Corrections

When a user corrects you, store it immediately with high importance:

```python
store_memory(
  content="User correction: Do NOT use `console.log` for debugging — use the project logger at `src/utils/logger.ts`.",
  namespace="user:alice",
  category="preference",
  importance=0.9,
  tags=["correction", "logging", "style"]
)
```

---

## Anti-Patterns

### What NOT to Store

| Bad | Why | Instead |
|---|---|---|
| Entire file contents | Too large, noisy, hard to search | Use `ingest_file` or store key facts only |
| Ephemeral task state | Not useful beyond current session | Skip — only store lasting knowledge |
| Redundant duplicates | Pollutes search results | Check with `search_memory` before storing |
| Raw stack traces | Unstructured, not retrievable | Store the resolution + root cause |
| Opinions without context | Ambiguous | Include the "why" in the content |

### Namespace Sprawl

Bad:
```
project:myapp-auth
project:myapp-api
project:myapp-frontend
```

Good:
```
project:myapp           # single namespace, use tags for subsystem
tags: ["auth"], ["api"], ["frontend"]
```

Use sub-namespaces only when the project genuinely splits into independent domains used by different teams.

### Over-Consolidation

Consolidating after every 1–2 memories produces trivial, noisy insights. Wait for 5+ substantive memories before consolidating. Consolidation is most useful after completing a feature, resolving a bug cluster, or ending a multi-session project phase.

### Stale Memory Accumulation

Periodically audit with `list_memories` and delete outdated entries:

```python
memories = list_memories(namespace="project:myapp", limit=50, category="fact")
# Review and call delete_memory(memory_id=...) for obsolete entries
```

---

## Importance Calibration Guide

| Scenario | Importance |
|---|---|
| "Never do X" hard constraint | 0.95 |
| Security requirement, compliance rule | 0.9 |
| Architecture decision affecting all code | 0.85 |
| User's repeated strong preference | 0.8 |
| Resolved production bug root cause | 0.75 |
| Standard project fact (tech stack, etc.) | 0.65 |
| Normal preference or style choice | 0.5 |
| Session summary, general episode | 0.5 |
| Tangential context, weak signal | 0.2 |
