# Red Team Review: Agent Memory MCP Server Plan

**Date**: 2026-03-16 14:30
**Severity**: High
**Component**: Plan validation, security & robustness
**Status**: Resolved

## What Happened

Four parallel adversarial reviewers tore apart the agent-memory MCP server plan with systematic rigor. 39 raw findings were produced, deduplicated to 15 unique issues across security, architecture, effort estimation, and scope. 14 were accepted and integrated into the plan; 1 was rejected as over-engineering for v1.

## The Brutal Truth

This hurt. The plan was fundamentally sound in vision but dangerously incomplete in threat modeling and execution realism. We were shipping a system with wide-open HTTP auth, no concurrency guards on consolidation, prompt injection vulnerabilities, and a 24-hour estimate that screamed inexperience. Four strangers found in parallel what internal review would have caught, but slower.

The worst part: these weren't edge cases. They were front-door vulnerabilities and architectural contradictions that would have surfaced immediately in production.

## Technical Details

**Critical findings (5):**
- HTTP server binding to 0.0.0.0 with CORS *, no authentication
- Consolidation prompts vulnerable to prompt injection via untrusted memory content
- ingest_file with no path traversal defense—arbitrary file reads possible
- Embedding dimension changes silently corrupted vector indices
- Consolidation writes were non-atomic, risking partial state corruption

**High-severity findings (7):**
- No asyncio.Lock guard on concurrent consolidation requests
- Unreliable JSON parsing from LLM consolidation without fallback validation
- 24-hour effort estimate was off by 40% (hidden risk buffer)
- Multimodal ingestion deferred to post-MVP but left in phase structure
- File watcher was pure YAGNI (deferred)
- Dashboard had no MVP users (deferred to post-MVP)
- Redundant embedding BLOB column + vec0 column created consistency risk

**Medium findings (3):**
- Namespace-level ACL was rejected (correct: local-first v1 doesn't need it yet)
- No graceful shutdown handler for SIGINT/SIGTERM
- Shared APIClient abstraction missing between embedding and LLM providers

## What We Tried

Red team was structured: Security Adversary (attacked auth, injection, file access), Assumption Destroyer (questioned multimodal, file watcher, dashboard), Failure Mode Analyst (embedding dims, consolidation atomicity, parsing reliability), Scope Critic (effort, premature abstractions, MVP creep).

Result: 39 findings. Manual dedup + severity assessment. Each finding mapped to a phase for implementation.

## Root Cause Analysis

The plan was built with optimism bias and architectural abstractions ahead of threat analysis. Key failures:

1. **Security last** — Auth, injection defense, path traversal were afterthoughts, not day-one requirements
2. **Effort blindness** — No buffer for concurrency guards, transactional writes, multi-layer validation
3. **Premature abstraction** — StorageAdapter ABC created complexity before a single concrete implementation existed
4. **MVP creep** — Multimodal, file watcher, dashboard were vague promises, not deferred; red team forced clarity
5. **No concurrency story** — Consolidation was single-threaded in design; blocking write corruption risk was real

## Lessons Learned

- **Threat model first** — HTTP server = must have auth, CORS, and TLS story before phase 1
- **Buffer realistically** — 24h = 16h code + 4h buffer + 4h learning. We did 16h + 0h + 8h hidden contingencies. Call it 28-40h upfront
- **Concrete over abstract** — SQLiteStorage first. StorageAdapter when we have two implementations
- **Scope discipline** — Post-MVP is a dump for vague ideas. Red team forced: multimodal → deferred, file watcher → deferred, dashboard → deferred
- **Concurrency is mandatory** — Any shared resource (consolidation state, vector index writes) needs a guard or it will corrupt under load
- **Validation layers matter** — LLM JSON parsing needs Pydantic + fallback + circuit breaker, not hope and try/catch

## Changes Applied

1. **HTTP auth**: Bind to 127.0.0.1 by default, CORS restricted to localhost, bearer token required for non-localhost
2. **Prompt injection**: XML-tagged CDATA delimiters for memory in prompts, system prompt marks content as untrusted, dedup flags only (no auto-delete)
3. **Consolidation**: Transactional writes, asyncio.Lock concurrency guard, circuit breaker for LLM failure, multi-layer JSON parsing with Pydantic validation
4. **Storage**: Dropped StorageAdapter ABC (premature), concrete SQLiteStorage only, metadata table for embedding dimension tracking, removed redundant BLOB column
5. **File ingestion**: ingest_file restricted to configurable allowed_paths allowlist with symlink resolution
6. **Architecture**: Shared APIClient utility for embedding and LLM providers, graceful shutdown manager for SIGINT/SIGTERM
7. **Effort**: Adjusted from 24h → 40h with realistic risk buffer
8. **Scope**: Multimodal, file watcher, dashboard explicitly deferred to post-MVP

## Next Steps

9 phase-level tasks now hydrated with dependency chain. Start phase 1 (project setup, HTTP auth, graceful shutdown infrastructure). Security review checkpoint before phase 4 (MCP server) ships. Load-test consolidation concurrency in phase 5.

This red team review saved us from shipping insecure code. The plan is now honest about effort, clear on threats, and disciplined on scope.
