---
title: "Open-source packaging for agent-memory"
description: "Make agent-memory PyPI-installable, skill-installable, and README-driven"
status: pending
priority: P1
effort: 3h
branch: main
tags: [packaging, open-source, pypi, mcp]
created: 2026-03-17
---

# Phase 10 — Open-Source Packaging

## Overview

Ship agent-memory as a proper open-source project: PyPI package, installable skill, polished README, CI/CD.

**Priority:** P1 — blocks all external adoption
**Status:** Pending

---

## 1. Rename package to `agent-memory-server`

### pyproject.toml changes

```toml
[project]
name = "agent-memory-server"

[project.scripts]
agent-memory-server = "agent_memory.__main__:main"
```

- Keep `agent-memory` as an additional script alias for backward compat (optional, low priority)
- Keep internal Python package as `agent_memory` (no rename of `src/agent_memory/`)
- Update `__main__.py` `prog` to `"agent-memory-server"`
- Bump version to `0.1.0` (already set, confirm before publish)

### Files to modify
- `pyproject.toml` — name, scripts entry
- `src/agent_memory/__main__.py` — prog name in argparse

---

## 2. Skill manifest for `npx skills add`

The `skills` CLI looks for skill files in the repo root or a `skill/` directory. Current structure already has `skill/SKILL.md`.

### Create `.claude-skill.json` in repo root

```json
{
  "name": "agent-memory",
  "description": "Persistent memory for AI agents via MCP",
  "skill_file": "skill/SKILL.md",
  "references": ["skill/references/memory-patterns.md"]
}
```

### Verify
- Confirm `npx skills add` reads from repo root manifest
- If CLI expects `SKILL.md` at root, add a symlink or move it — but check first

### Files to create
- `.claude-skill.json`

---

## 3. README.md rewrite

This is the highest-leverage artifact. Structure:

```markdown
# agent-memory-server

Persistent memory for AI agents — MCP server with semantic search,
namespaced storage, and automatic consolidation.

## Quick Install (AI Agent)

# Add as MCP server (zero-install via uvx)
claude mcp add agent-memory -- uvx agent-memory-server

# Or install the skill for memory best practices
npx skills add owner/agent-memory -g

## Quick Install (Human)

pip install agent-memory-server
agent-memory-server --transport stdio

## MCP Configuration

### Claude Code (CLI)
claude mcp add --transport stdio agent-memory -- uvx agent-memory-server

### Claude Code (JSON) — ~/.claude.json
{
  "mcpServers": {
    "agent-memory": {
      "command": "uvx",
      "args": ["agent-memory-server"]
    }
  }
}

### With config file
{
  "mcpServers": {
    "agent-memory": {
      "command": "uvx",
      "args": ["agent-memory-server", "--config", "~/.agent-memory/config.yaml"]
    }
  }
}

## Configuration

Zero-config works out of the box (SQLite at ~/.agent-memory/memory.db,
no embeddings, no consolidation).

For semantic search, set an embedding provider:
  export AGENT_MEMORY_EMBEDDING__PROVIDER=openai
  export AGENT_MEMORY_EMBEDDING__API_KEY=sk-...

See config.example.yaml for all options.

## Tools

[Table of MCP tools: store, search, list, update, delete, consolidate,
ingest_text, ingest_file, get_stats]

## Development

git clone ...
cd agent-memory
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest

## License
MIT
```

### Key principles
- First 10 lines must tell an AI agent exactly what to run
- Copy-pasteable commands, no prose between command blocks
- `claude mcp add` is the primary install path
- Config snippets for both CLI and JSON approaches

### Files to modify
- `README.md` — full rewrite

---

## 4. GitHub repo files

### LICENSE (MIT)
- Create `LICENSE` file with MIT text, copyright `2026 {author}`

### .gitignore
- Create `.gitignore` with Python defaults: `__pycache__/`, `*.pyc`, `.venv/`,
  `dist/`, `*.egg-info/`, `.coverage`, `.pytest_cache/`, `.ruff_cache/`,
  `*.db`, `.env`

### Files to create
- `LICENSE`
- `.gitignore`

---

## 5. GitHub Actions CI

### `.github/workflows/ci.yml`
- Trigger: push to main, PRs
- Matrix: Python 3.11, 3.12, 3.13
- Steps: checkout, setup-python, `pip install -e ".[dev]"`, `ruff check .`, `pytest`

### `.github/workflows/publish.yml`
- Trigger: GitHub release created
- Steps: checkout, setup-python, build (`python -m build`), publish to PyPI via `pypa/gh-action-pypi-publish`
- Requires `PYPI_API_TOKEN` secret configured on repo

### Files to create
- `.github/workflows/ci.yml`
- `.github/workflows/publish.yml`

### pyproject.toml addition
Add `build` to dev dependencies:
```toml
[project.optional-dependencies]
dev = [
    ...existing...,
    "build>=1.0",
]
```

---

## Implementation Order

| Step | Task | Depends on |
|------|------|------------|
| 1 | `.gitignore` + `LICENSE` | — |
| 2 | Rename package in `pyproject.toml` + `__main__.py` | — |
| 3 | Create `.claude-skill.json` | — |
| 4 | Rewrite `README.md` | Steps 2-3 (need final names) |
| 5 | GitHub Actions CI + publish workflows | Step 2 (need final package name) |
| 6 | Verify: `pip install -e .` still works, tests pass, `agent-memory-server` CLI runs | All |

Steps 1-3 can run in parallel. Step 4-5 after names finalized. Step 6 is validation.

---

## Todo List

- [ ] Create `.gitignore`
- [ ] Create `LICENSE` (MIT)
- [ ] Update `pyproject.toml`: name -> `agent-memory-server`, add script entry
- [ ] Update `__main__.py`: prog name
- [ ] Create `.claude-skill.json` manifest
- [ ] Rewrite `README.md`
- [ ] Create `.github/workflows/ci.yml`
- [ ] Create `.github/workflows/publish.yml`
- [ ] Run `pip install -e .` and verify CLI works
- [ ] Run `pytest` — confirm 109 tests still pass
- [ ] Run `ruff check .` — clean lint

---

## Success Criteria

1. `pip install agent-memory-server` installs and `agent-memory-server` CLI starts
2. `claude mcp add agent-memory -- uvx agent-memory-server` works
3. `npx skills add owner/agent-memory -g` installs skill
4. README is self-sufficient for both AI agents and humans
5. CI runs on push, publish runs on release
6. All 109 existing tests pass without modification

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| PyPI name `agent-memory-server` taken | Low | Check with `pip index versions agent-memory-server` before publishing |
| `skills` CLI expects different manifest format | Medium | Test locally with `npx skills add ./` before push |
| `uvx` fails to resolve new package name | Low | Test after first PyPI publish; `uvx` resolves from PyPI name |

---

## What NOT to change

- Internal Python package stays `agent_memory` (in `src/agent_memory/`)
- No code changes to server, storage, embedding, consolidation, ingestion
- No test modifications
- `config.example.yaml` stays as-is
- `skill/SKILL.md` content stays as-is
