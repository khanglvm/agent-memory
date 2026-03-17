"""Vault REST API — standalone Starlette app on separate port."""

from __future__ import annotations

import hashlib
import hmac
import logging
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


class _AuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token on vault API routes (skips /health)."""

    def __init__(self, app: object, auth_token: str | None) -> None:
        super().__init__(app)
        self._auth_token = auth_token

    async def dispatch(self, request: Request, call_next: object) -> JSONResponse:
        # Skip auth for health check
        if request.url.path == "/health":
            return await call_next(request)
        if self._auth_token:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or not hmac.compare_digest(
                auth[7:], self._auth_token
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


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
        """Return memories modified since ?since= timestamp."""
        since = request.query_params.get("since", "1970-01-01T00:00:00+00:00")
        namespace = request.query_params.get("namespace")
        limit = min(int(request.query_params.get("limit", "100")), 500)
        offset = max(int(request.query_params.get("offset", "0")), 0)

        all_changes = await storage.get_changes_since(since, namespace)
        total = len(all_changes)
        page = all_changes[offset : offset + limit]

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
            "count": len(page),
            "total": total,
            "since": since,
            "limit": limit,
            "offset": offset,
        })

    async def delete_memory_route(request: Request) -> JSONResponse:
        """Delete memory by ID."""
        memory_id = request.path_params["id"]
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
        Middleware(_AuthMiddleware, auth_token=config.server.auth_token),
    ]

    return Starlette(routes=routes, middleware=middleware)
