# Phase 8: Agent Skill

## Context Links
- [Phase 4: MCP Tools](./phase-04-mcp-server-tools.md)
- Skill Creator standard at `~/.claude/skills/skill-creator/SKILL.md`

## Overview
- **Priority:** P2 (Medium)
- **Status:** Complete
- **Effort:** 2h (actual: ~2h)
- **Description:** Agent Skill (skill-creator standard) so agents know how to use the MCP properly. Dashboard deferred to post-MVP.

## Red Team Findings Applied
- **[RT-11]** Dashboard cut from MVP: agents don't use dashboards, MCP inspector + stats tool suffice for v1. Dashboard is post-MVP.

## Key Insights
- Agent Skill is critical: without it, agents try-and-fail with memory tools
- Skill teaches agents: when to store, what to search, how to namespace, consolidation patterns
- Skill follows `~/.claude/skills/` standard with `SKILL.md`
- Keep skill concise — agents have limited context

## Requirements

### Functional
- `SKILL.md` — agent instructions for using the memory MCP
- Covers: when to store memories, search patterns, namespace conventions, consolidation triggers
- Tool usage examples with proper parameter patterns
- Installed as Claude Code skill (or any agent's equivalent)

### Non-Functional
- Skill should be concise — agents have limited context
- Reference tool descriptions to stay up-to-date

## Related Code Files

### Files to Create
- `skill/SKILL.md` — Agent skill definition
- `skill/references/memory-patterns.md` — Usage patterns reference

## Implementation Steps

1. Create `skill/SKILL.md` following skill-creator standard:
   ```markdown
   # Agent Memory Skill

   ## When to Use
   - Store important facts, user preferences, project context
   - Search past knowledge before starting new tasks
   - Consolidate after accumulating 5+ new memories

   ## Tool Usage Patterns

   ### Storing Memories
   - Use `store_memory` with clear, atomic facts
   - Choose correct category: fact, preference, procedure, episode
   - Set importance: 0.8+ for critical, 0.5 for normal, 0.2 for background

   ### Searching
   - Use `search_memory` with natural language queries
   - Filter by namespace for project-specific context
   - Search BEFORE starting new tasks to leverage past knowledge

   ### Namespacing
   - `global` — cross-project knowledge
   - `project:{name}` — project-specific context
   - `user:{name}` — user preferences and traits

   ### Consolidation
   - Trigger after 5+ new memories in a namespace
   - Review consolidation insights for patterns
   ```

2. Create `skill/references/memory-patterns.md` with detailed examples

## Todo List
- [x] Create `skill/SKILL.md`
- [x] Create `skill/references/memory-patterns.md`
- [x] Validate skill against actual tool schemas

## Success Criteria
- Agent skill teaches correct tool usage patterns
- Skill follows skill-creator standard format
- Skill is concise enough for agent context windows

## Risk Assessment
- **Skill maintenance:** As tools evolve, skill becomes stale. Mitigate: keep skill minimal, reference tool descriptions.

## Security Considerations
- No secrets in skill files
