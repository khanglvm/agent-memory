---
name: agent-memory
description: Persistent memory for AI agents via MCP. Use when you need to remember facts, preferences, procedures, or decisions across sessions. Activate before starting tasks to search past knowledge, and after learning something new to store it.
metadata:
  author: khanglvm
  version: "0.1.0"
  tags: ["memory", "mcp", "persistence", "knowledge"]
---

# Agent Memory Skill

MCP server that gives agents persistent memory across sessions.
Activate this skill when you need to remember or recall information beyond your context window.

## When to Use

**Store** when you encounter:
- User preferences, names, constraints, or repeated instructions
- Project decisions, architecture choices, or established patterns
- Procedures you've figured out (setup steps, workflows)
- Errors resolved and their solutions
- Facts that are likely to be needed in future sessions

**Search** before:
- Starting any task in a familiar project or with a known user
- Answering questions about past decisions or preferences
- Repeating work you may have done before

**Consolidate** after:
- Accumulating 5+ new memories in a namespace
- Completing a significant work session

---

## Namespacing

| Pattern | Use case |
|---|---|
| `global` | Cross-project knowledge, general user preferences |
| `project:{name}` | Project-specific context, decisions, architecture |
| `user:{name}` | Individual user traits, communication preferences |

Default namespace is `default`. Use specific namespaces to keep knowledge scoped.

---

## Categories

| Category | When |
|---|---|
| `fact` | Objective facts — project names, tech stack, constraints |
| `preference` | User or project style choices |
| `procedure` | How-to steps, repeatable workflows |
| `episode` | What happened in a session, decisions made, errors resolved |

---

## Importance

| Value | Use case |
|---|---|
| `0.8–1.0` | Critical — user hard requirements, security constraints, breaking decisions |
| `0.5` | Normal — standard facts and preferences |
| `0.2` | Background — minor context, low-confidence observations |

---

## Tool Quick Reference

### store_memory
```
store_memory(
  content="<atomic fact or observation>",
  namespace="project:myapp",
  category="fact",           # fact | preference | procedure | episode
  tags=["auth", "postgres"], # optional, helps filtering
  importance=0.5             # 0.0–1.0
)
```
Returns: `memory_id`, confirmation.

### search_memory
```
search_memory(
  query="<natural language question>",
  namespace="project:myapp", # optional, scopes search
  top_k=5,                   # default 10
  category="fact"            # optional filter
)
```
Returns: ranked list of `{id, content, summary, similarity, category, created_at}`.

### list_memories
```
list_memories(
  namespace="project:myapp",
  limit=20,
  offset=0,
  category="preference"  # optional
)
```
Use for browsing known memories when you don't have a specific query.

### update_memory
```
update_memory(
  memory_id="<uuid>",
  content="<revised content>",   # optional
  importance=0.8,                # optional
  category="fact"                # optional
)
```
Re-embeds automatically if content changes.

### delete_memory
```
delete_memory(memory_id="<uuid>")
```
Use when a memory is outdated or incorrect.

### get_memory_stats
```
get_memory_stats(namespace="project:myapp")  # omit for global stats
```
Returns: totals, category breakdown, unconsolidated count.

### consolidate_memories
```
consolidate_memories(namespace="project:myapp")
```
Finds patterns and produces insights. Trigger after 5+ new memories.

### ingest_text / ingest_file
```
ingest_text(text="<long doc>", source="meeting-notes", namespace="project:myapp")
ingest_file(file_path="/abs/path/to/file.md", namespace="project:myapp")
```
Chunks and stores large content automatically.

---

## MCP Resources (read-only context)

| URI | Returns |
|---|---|
| `memory://stats` | Global stats across all namespaces |
| `memory://recent/{namespace}` | Last 10 memories in namespace |
| `memory://namespaces` | All known namespaces |
| `memory://consolidations/{namespace}` | Recent consolidation insights |

---

## Standard Workflow

```
1. Session start  → search_memory(query="context for <project/user>")
2. Learn something → store_memory(content=..., category=..., importance=...)
3. After 5+ stores → consolidate_memories(namespace=...)
4. Session end    → store_memory(content="session summary", category="episode")
```

See `references/memory-patterns.md` for detailed workflow examples.
