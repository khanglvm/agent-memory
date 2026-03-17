# Phase 3: Embedding Provider System

## Context Links
- [Phase 1: Config](./phase-01-project-setup.md)
- [Phase 2: Storage](./phase-02-storage-layer.md)

## Overview
- **Priority:** P1 (Critical)
- **Status:** Complete
- **Effort:** 2h
- **Description:** Configurable embedding provider system — user provides endpoint + API key, also supports Ollama/local runtimes.

## Key Insights
- User validated: configurable provider endpoint + API key, also Ollama support
- Most embedding APIs follow OpenAI-compatible format (`/v1/embeddings`)
- Ollama exposes same-ish format at `/api/embeddings`
- Keep provider interface simple: `text in → vector out`

## Red Team Findings Applied
- **[RT-15]** Create shared `APIClient` utility for HTTP calls, auth, retries, rate limits. Both `EmbeddingProvider` and `LLMProvider` (Phase 5) use it — no duplicated HTTP logic.
- **[RT-4]** Enforce HTTPS when `api_key` is set (hard error, not warning). Allow HTTP only when no key or explicit `allow_insecure: true`.

## Requirements

### Functional
- `EmbeddingProvider` ABC with `embed(text) -> list[float]` and `embed_batch(texts) -> list[list[float]]`
- OpenAI-compatible provider (works with OpenAI, Together, Fireworks, vLLM, LiteLLM)
- Ollama provider (local embeddings)
- Configurable via YAML: base_url, api_key, model name, dimensions
- Optional: skip embeddings entirely (recency-based fallback)

### Non-Functional
- Batch support for efficiency
- Timeout + retry with backoff
- Graceful degradation when provider unavailable

## Architecture

```python
class EmbeddingProvider(ABC):
    @property
    def dimensions(self) -> int: ...
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

class OpenAICompatibleProvider(EmbeddingProvider):
    """Works with any OpenAI-compatible endpoint"""
    def __init__(self, base_url, api_key, model, dimensions): ...

class OllamaProvider(EmbeddingProvider):
    """Local Ollama embeddings"""
    def __init__(self, base_url, model): ...

class NoopProvider(EmbeddingProvider):
    """No embeddings — fallback to recency-based retrieval"""
    ...
```

Config example:
```yaml
embedding:
  provider: openai  # openai | ollama | none
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}  # env var substitution
  model: text-embedding-3-small
  dimensions: 1536
```

## Related Code Files

### Files to Create
- `src/agent_memory/http_client.py` — **[RT-15]** Shared APIClient (retries, auth, rate limits)
- `src/agent_memory/embedding/base.py` — EmbeddingProvider ABC
- `src/agent_memory/embedding/providers.py` — OpenAI-compatible, Ollama, Noop providers
- `tests/test_embedding.py` — provider tests

### Files to Modify
- `src/agent_memory/embedding/__init__.py` — export factory
- `src/agent_memory/config.py` — add embedding config section

## Implementation Steps

1. Implement `EmbeddingProvider` ABC in `base.py`
2. Implement `OpenAICompatibleProvider`:
   - Use `httpx.AsyncClient` for HTTP calls
   - POST to `{base_url}/embeddings` with `{"model": ..., "input": ...}`
   - Handle rate limits (429) with exponential backoff
   - Validate response dimensions match config
3. Implement `OllamaProvider`:
   - POST to `{base_url}/api/embeddings` with `{"model": ..., "prompt": ...}`
   - No auth needed (local)
   - Auto-detect dimensions from first response
4. Implement `NoopProvider`:
   - Returns empty list — signals storage to skip vector operations
5. Implement factory:
   ```python
   def create_provider(config: EmbeddingConfig) -> EmbeddingProvider:
       match config.provider:
           case "openai": return OpenAICompatibleProvider(...)
           case "ollama": return OllamaProvider(...)
           case "none" | None: return NoopProvider()
   ```
6. Write tests with httpx mock responses

## Todo List
- [x] Implement shared `APIClient` with retries, auth, rate limits
- [x] Implement `EmbeddingProvider` ABC
- [x] Implement `OpenAICompatibleProvider` (using shared APIClient)
- [x] Implement `OllamaProvider` (using shared APIClient)
- [x] Implement `NoopProvider`
- [x] Implement provider factory
- [x] Enforce HTTPS when api_key is set
- [x] Add embedding config to `config.py`
- [x] Write tests with mocked HTTP responses
- [x] Test graceful degradation (provider down)

## Success Criteria
- OpenAI-compatible provider generates embeddings via HTTP
- Ollama provider works with local models
- Noop provider allows server to run without any embedding config
- Batch embed reduces round trips
- Tests pass with mocked responses

## Risk Assessment
- **Provider API changes:** Use standard OpenAI format as baseline. Mitigate: abstract behind interface.
- **Dimension mismatch:** If user changes model mid-run, vectors are incompatible. Mitigate: store dim in DB metadata, warn on mismatch.

## Security Considerations
- API keys only via env vars, never logged
- Validate base_url is HTTPS (warn on HTTP)
- Sanitize text before sending to external API (strip PII if configured)
