"""Vault REST API — standalone Starlette app on separate port."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent_memory.vault.serializer import (
    markdown_to_memory,
    memory_to_markdown,
)

if TYPE_CHECKING:
    from agent_memory.config import MemoryConfig
    from agent_memory.embedding.base import EmbeddingProvider
    from agent_memory.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_BATCH_SIZE = 100

_SAFE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,99}$')
_UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _validate_memory_input(memory: object, max_content_length: int) -> str | None:
    """Return error message if invalid, None if OK.

    ID validation: if the string matches UUID segment length/structure (32+ hex chars
    with dashes) it must be a well-formed UUID; otherwise it must match _SAFE_NAME_PATTERN.
    """
    if len(memory.content.encode('utf-8')) > max_content_length:
        return f"content exceeds max length ({max_content_length} bytes)"
    if memory.id:
        # Detect UUID-like strings: 32 hex chars + 4 dashes = 36 chars total
        _is_uuid_shaped = (
            len(memory.id) == 36
            and memory.id.count('-') == 4
            and all(c in '0123456789abcdefABCDEF-' for c in memory.id)
        )
        if _is_uuid_shaped and not _UUID_PATTERN.match(memory.id):
            return f"invalid memory ID format: {memory.id}"
        if not _is_uuid_shaped and not _SAFE_NAME_PATTERN.match(memory.id):
            return f"invalid memory ID format: {memory.id}"
    if not _SAFE_NAME_PATTERN.match(memory.namespace):
        return f"invalid namespace: {memory.namespace}"
    if not _SAFE_NAME_PATTERN.match(memory.category):
        return f"invalid category: {memory.category}"
    return None


class _RateLimiter:
    """Sliding window rate limiter keyed by client identifier."""

    _CLEANUP_INTERVAL = 300  # purge stale keys every 5 minutes

    def __init__(self, max_requests: int = 100, window_sec: int = 60) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        window_start = now - self.window_sec

        # Periodic cleanup of stale keys
        if now - self._last_cleanup > self._CLEANUP_INTERVAL:
            stale = [k for k, v in self._requests.items() if not v or v[-1] < window_start]
            for k in stale:
                del self._requests[k]
            self._last_cleanup = now

        reqs = self._requests[client_id]
        self._requests[client_id] = [t for t in reqs if t > window_start]
        if len(self._requests[client_id]) >= self.max_requests:
            return False
        self._requests[client_id].append(now)
        return True


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """Block requests exceeding rate limit threshold (skips /health)."""

    def __init__(self, app: object, rate_limiter: _RateLimiter) -> None:
        super().__init__(app)
        self._limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: object) -> JSONResponse:
        if request.url.path == "/health":
            return await call_next(request)
        client_id = request.headers.get(
            "Authorization",
            request.client.host if request.client else "unknown",
        )
        if not self._limiter.is_allowed(client_id):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
        return await call_next(request)


class _AuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token on vault API routes (skips /health).

    Accepts both current and previous token to support zero-downtime rotation.
    """

    def __init__(
        self,
        app: object,
        auth_token: str | None,
        auth_token_previous: str | None = None,
    ) -> None:
        super().__init__(app)
        self._auth_token = auth_token
        self._auth_token_previous = auth_token_previous

    async def dispatch(self, request: Request, call_next: object) -> JSONResponse:
        if request.url.path == "/health":
            return await call_next(request)
        if self._auth_token:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            token = auth[7:]
            valid = hmac.compare_digest(token, self._auth_token)
            if not valid and self._auth_token_previous:
                valid = hmac.compare_digest(token, self._auth_token_previous)
            if not valid:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


class _AuditMiddleware(BaseHTTPMiddleware):
    """Log all vault API requests with method, path, client, and status (skips /health)."""

    async def dispatch(self, request: Request, call_next: object) -> JSONResponse:
        response = await call_next(request)
        if request.url.path != "/health":
            client = request.client.host if request.client else "unknown"
            logger.info(
                "VAULT_AUDIT %s %s client=%s status=%d",
                request.method,
                request.url.path,
                client,
                response.status_code,
            )
        return response


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def create_vault_app(
    storage: SQLiteStorage,
    embedding_provider: EmbeddingProvider,
    config: MemoryConfig,
) -> Starlette:
    """Create standalone Starlette app for vault sync API."""

    async def _upsert_memory(markdown: str) -> dict:
        """Shared upsert logic for push and batch-push.

        Returns a result dict with memory_id, status, and optionally updated_at.
        """
        memory = markdown_to_memory(markdown)

        # Input validation
        error = _validate_memory_input(memory, config.vault.max_content_length)
        if error:
            raise ValueError(error)

        # Idempotent check via content hash
        existing = await storage.get(memory.id)
        if existing and _content_hash(existing.content) == _content_hash(memory.content):
            return {
                "memory_id": memory.id,
                "status": "unchanged",
                "updated_at": existing.updated_at,
            }

        memory.updated_at = datetime.now(timezone.utc).isoformat()

        # Generate embedding
        embedding = None
        if embedding_provider.dimensions > 0:
            try:
                embedding = await embedding_provider.embed(memory.content)
            except Exception as exc:
                logger.warning("Failed to generate embedding: %s", exc)

        memory_id = await storage.store(memory, embedding=embedding)

        # Write .md to vault if enabled
        if config.vault.write_on_store and config.vault.vault_path:
            from agent_memory.vault.writer import write_memory_to_vault

            try:
                await write_memory_to_vault(memory, config.vault)
            except Exception as exc:
                logger.warning("Failed to write vault file: %s", exc)

        return {
            "memory_id": memory_id,
            "status": "updated" if existing else "created",
            "updated_at": memory.updated_at,
        }

    async def push_memory(request: Request) -> JSONResponse:
        """Accept .md content from Obsidian plugin, upsert into SQLite."""
        # Body size check
        content_length = int(request.headers.get("content-length", 0))
        if content_length > MAX_BODY_SIZE:
            return JSONResponse({"error": "payload too large"}, status_code=413)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        markdown = body.get("markdown")
        if not markdown:
            return JSONResponse({"error": "missing 'markdown' field"}, status_code=400)

        try:
            result = await _upsert_memory(markdown)
        except ValueError as exc:
            return JSONResponse({"error": f"parse error: {exc}"}, status_code=400)

        return JSONResponse(result)

    async def get_changes(request: Request) -> JSONResponse:
        """Return memories modified since ?since= timestamp, including tombstones."""
        since = request.query_params.get("since", "1970-01-01T00:00:00+00:00")
        namespace = request.query_params.get("namespace")
        try:
            limit = min(int(request.query_params.get("limit", "100")), 500)
            offset = max(int(request.query_params.get("offset", "0")), 0)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": "limit and offset must be integers"}, status_code=400
            )

        all_changes = await storage.get_changes_since(since, namespace)
        total = len(all_changes)
        page = all_changes[offset : offset + limit]

        # Include tombstones (deleted records) for sync propagation
        tombstones = await storage.get_tombstones_since(since, namespace)

        return JSONResponse({
            "changes": [
                {
                    "id": m.id,
                    "namespace": m.namespace,
                    "category": m.category,
                    "updated_at": m.updated_at,
                    "content_hash": _content_hash(m.content),
                    "markdown": memory_to_markdown(m),
                }
                for m in page
            ],
            "deleted": [
                {
                    "id": t["id"],
                    "namespace": t["namespace"],
                    "deleted_at": t["deleted_at"],
                }
                for t in tombstones
            ],
            "count": len(page),
            "total": total,
            "since": since,
            "limit": limit,
            "offset": offset,
        })

    async def delete_memory_route(request: Request) -> JSONResponse:
        """Delete memory by ID."""
        memory_id = request.path_params["id"]
        # Validate ID format
        if not _SAFE_NAME_PATTERN.match(memory_id) and not _UUID_PATTERN.match(memory_id):
            return JSONResponse(
                {"error": f"invalid memory ID format: {memory_id}"}, status_code=400
            )
        deleted = await storage.delete(memory_id)
        return JSONResponse({
            "memory_id": memory_id,
            "status": "deleted" if deleted else "not_found",
        })

    async def batch_push(request: Request) -> JSONResponse:
        """Accept multiple .md files in one request."""
        content_length = int(request.headers.get("content-length", 0))
        if content_length > MAX_BODY_SIZE:
            return JSONResponse({"error": "payload too large"}, status_code=413)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        files = body.get("files", [])
        if not isinstance(files, list):
            return JSONResponse({"error": "'files' must be a list"}, status_code=400)
        if len(files) > MAX_BATCH_SIZE:
            return JSONResponse(
                {"error": f"batch size exceeds limit ({MAX_BATCH_SIZE})"},
                status_code=400,
            )

        results = []
        for item in files:
            markdown = item.get("markdown", "")
            if not markdown:
                results.append({"error": "missing markdown", "status": "skipped"})
                continue

            try:
                result = await _upsert_memory(markdown)
                results.append(result)
            except ValueError as exc:
                results.append({"error": str(exc), "status": "parse_error"})

        return JSONResponse({"results": results, "total": len(results)})

    async def health(request: Request) -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse({"status": "ok", "service": "agent-memory-vault"})

    routes = [
        Route("/api/vault/push", push_memory, methods=["POST"]),
        Route("/api/vault/changes", get_changes, methods=["GET"]),
        Route("/api/vault/memories/{id}", delete_memory_route, methods=["DELETE"]),
        Route("/api/vault/batch-push", batch_push, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]

    middleware = [
        Middleware(_AuditMiddleware),
        Middleware(
            _RateLimitMiddleware,
            rate_limiter=_RateLimiter(
                max_requests=config.vault.rate_limit_max,
                window_sec=config.vault.rate_limit_window_sec,
            ),
        ),
        Middleware(
            _AuthMiddleware,
            auth_token=config.server.auth_token,
            auth_token_previous=config.server.auth_token_previous,
        ),
    ]

    return Starlette(routes=routes, middleware=middleware)
