# Phase 6: Text Ingestion

## Context Links
- [Phase 5: Consolidation](./phase-05-consolidation-engine.md)

## Overview
- **Priority:** P2 (Medium)
- **Status:** Complete
- **Effort:** 2h (actual: ~2h)
- **Description:** Text-only file ingestion pipeline. Multimodal (images/audio/video) and file watcher deferred to post-MVP.

## Red Team Findings Applied
- **[RT-3]** Path traversal defense: `ingest_file` restricted to configurable `allowed_paths` allowlist. Resolve symlinks before checking. Reject anything outside.
- **[RT-9]** Cut multimodal: LLMProvider has no multimodal signature. Text-only for MVP.
- **[RT-10]** Cut file watcher: `ingest_file` MCP tool is sufficient. Watcher adds race conditions for unproven demand.

## Key Insights
- Text ingestion covers the primary use case (code files, notes, configs, logs)
- LLM extraction optional — store raw text with minimal metadata when no LLM configured
- Path restriction is critical security boundary

## Requirements

### Functional
- `ingest_file` MCP tool — accept file path (within allowed_paths), extract content, store as memory
- `ingest_text` MCP tool — accept raw text + source label
- Support text files only: `.txt, .md, .json, .csv, .yaml, .yml, .xml, .log`
- Deduplication: skip already-processed files (by content hash)

### Non-Functional
- Max file size: configurable (default 1MB for text)
- Path restriction enforced before any file read

## Architecture

```python
class IngestionProcessor:
    def __init__(self, storage, embedding_provider, llm_provider, config): ...
    async def ingest_text(self, text: str, source: str, namespace: str) -> str: ...
    async def ingest_file(self, path: Path, namespace: str) -> str: ...
    def _validate_path(self, path: Path) -> Path: ...  # resolve + allowlist check
```

## Related Code Files

### Files to Create
- `src/agent_memory/ingestion/processor.py` — IngestionProcessor
- `tests/test_ingestion.py`

### Files to Modify
- `src/agent_memory/server.py` — add ingest tools
- `src/agent_memory/config.py` — add ingestion config

## Implementation Steps

1. Implement `IngestionProcessor`:
   - `_validate_path`: resolve symlinks, check against `allowed_paths` allowlist, reject if outside
   - `ingest_text`: extract entities/topics via LLM (if configured) → embed → store
   - `ingest_file`: validate path → detect type (text only) → read content → extract → store
   - Dedup by content hash (SHA-256) in `processed_files` table

2. Text extraction prompt (reuse consolidation LLM):
   ```
   Extract from this content:
   1. A 1-2 sentence summary
   2. Key entities (people, companies, concepts)
   3. 2-4 topic tags
   4. Importance (0.0-1.0)
   Return ONLY valid JSON: {summary, entities, topics, importance}
   ```

3. Add MCP tools:
   - `ingest_text(text, source, namespace)` — process text into memory
   - `ingest_file(file_path, namespace)` — validate path, process file into memory

4. Config:
   ```yaml
   ingestion:
     allowed_paths: []  # REQUIRED for ingest_file — empty = tool disabled
     max_file_size_mb: 1
     supported_extensions: [.txt, .md, .json, .csv, .yaml, .yml, .xml, .log]
   ```

## Todo List
- [x] Implement path validation with allowlist + symlink resolution
- [x] Implement `IngestionProcessor.ingest_text()`
- [x] Implement `IngestionProcessor.ingest_file()` (text-only)
- [x] Implement content hash deduplication
- [x] Add `ingest_text` and `ingest_file` MCP tools
- [x] Add ingestion config section
- [x] Write tests (including path traversal rejection tests)

## Success Criteria
- Text ingestion extracts entities/topics and stores with embedding
- Path traversal attempts rejected with clear error
- Files outside allowed_paths rejected
- Processed files not re-ingested (content hash dedup)
- Graceful fallback when no LLM configured (raw text storage)

## Risk Assessment
- **LLM required for extraction:** Without LLM, ingestion stores raw text with basic metadata. Acceptable for MVP.

## Security Considerations
- **[RT-3]** Allowlist enforcement: resolve symlinks, reject outside allowed_paths
- `ingest_file` disabled when `allowed_paths` is empty (safe default)
- Sanitize extracted content before storage
