"""Tests for vault security — rate limiting, auth rotation,
input validation, audit logging."""

from __future__ import annotations

import asyncio
import logging

import pytest
from starlette.testclient import TestClient

from agent_memory.config import MemoryConfig, ServerConfig, StorageConfig, VaultConfig
from agent_memory.embedding.base import EmbeddingProvider
from agent_memory.models import Memory
from agent_memory.storage.sqlite import SQLiteStorage
from agent_memory.vault.routes import create_vault_app
from agent_memory.vault.serializer import memory_to_markdown

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NoOpEmbedding(EmbeddingProvider):
    def __init__(self, dimensions: int = 0) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        return []


def _make_storage(tmp_db_path: str) -> SQLiteStorage:
    config = StorageConfig(db_path=tmp_db_path)
    storage = SQLiteStorage(config, embedding_dim=0)
    asyncio.run(storage.initialize())
    return storage


def _make_valid_markdown(memory_id: str | None = None) -> str:
    """Return valid markdown for a memory with a UUID id."""
    kwargs: dict = {"content": "Hello world", "category": "fact", "namespace": "default"}
    if memory_id:
        kwargs["id"] = memory_id
    memory = Memory(**kwargs)
    return memory_to_markdown(memory)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def security_app(tmp_db_path: str) -> tuple[TestClient, SQLiteStorage]:
    """Vault app with tight rate limit and auth token rotation enabled."""
    storage = _make_storage(tmp_db_path)
    config = MemoryConfig(
        server=ServerConfig(auth_token="current-token", auth_token_previous="old-token"),
        vault=VaultConfig(
            enabled=True,
            rate_limit_max=5,
            rate_limit_window_sec=60,
            max_content_length=512,
        ),
    )
    app = create_vault_app(storage, _NoOpEmbedding(), config)
    client = TestClient(app)
    yield client, storage
    asyncio.run(storage.close())


@pytest.fixture
def no_auth_app(tmp_db_path: str) -> tuple[TestClient, SQLiteStorage]:
    """Vault app without auth token (default open access)."""
    storage = _make_storage(tmp_db_path)
    config = MemoryConfig(
        server=ServerConfig(auth_token=None),
        vault=VaultConfig(
            enabled=True,
            rate_limit_max=5,
            rate_limit_window_sec=60,
            max_content_length=512,
        ),
    )
    app = create_vault_app(storage, _NoOpEmbedding(), config)
    client = TestClient(app)
    yield client, storage
    asyncio.run(storage.close())


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Rate limiter blocks requests above threshold."""

    def test_requests_within_limit_succeed(
        self, no_auth_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """First N requests (≤ limit) should all return non-429."""
        client, _ = no_auth_app
        for i in range(5):
            md = _make_valid_markdown()
            resp = client.post("/api/vault/push", json={"markdown": md})
            assert resp.status_code != 429, f"Request {i} was unexpectedly rate-limited"

    def test_request_exceeding_limit_returns_429(
        self, no_auth_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Request after limit is reached should return 429."""
        client, _ = no_auth_app
        # Exhaust limit (5 max)
        for _ in range(5):
            md = _make_valid_markdown()
            client.post("/api/vault/push", json={"markdown": md})

        # This one should be rate-limited
        md = _make_valid_markdown()
        resp = client.post("/api/vault/push", json={"markdown": md})
        assert resp.status_code == 429
        assert "rate limit exceeded" in resp.json()["error"]

    def test_health_endpoint_bypasses_rate_limit(
        self, no_auth_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Health check should never be rate-limited."""
        client, _ = no_auth_app
        # Exhaust limit
        for _ in range(5):
            md = _make_valid_markdown()
            client.post("/api/vault/push", json={"markdown": md})

        # Health must still respond 200
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth Token Rotation
# ---------------------------------------------------------------------------

class TestAuthTokenRotation:
    """Both current and previous tokens must be accepted during rotation."""

    def test_current_token_accepted(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Current auth token should allow access."""
        client, _ = security_app
        md = _make_valid_markdown()
        resp = client.post(
            "/api/vault/push",
            json={"markdown": md},
            headers={"Authorization": "Bearer current-token"},
        )
        assert resp.status_code == 200

    def test_previous_token_accepted(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Previous auth token should still allow access during rotation window."""
        client, _ = security_app
        md = _make_valid_markdown()
        resp = client.post(
            "/api/vault/push",
            json={"markdown": md},
            headers={"Authorization": "Bearer old-token"},
        )
        assert resp.status_code == 200

    def test_invalid_token_rejected(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """An unrecognized token should return 401."""
        client, _ = security_app
        md = _make_valid_markdown()
        resp = client.post(
            "/api/vault/push",
            json={"markdown": md},
            headers={"Authorization": "Bearer totally-wrong"},
        )
        assert resp.status_code == 401
        assert "unauthorized" in resp.json()["error"]

    def test_missing_auth_returns_401(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Request without Authorization header should return 401."""
        client, _ = security_app
        md = _make_valid_markdown()
        resp = client.post("/api/vault/push", json={"markdown": md})
        assert resp.status_code == 401

    def test_health_bypasses_auth(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Health endpoint should not require auth."""
        client, _ = security_app
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    """Invalid inputs return 400 with descriptive messages."""

    def _push(self, client: TestClient, markdown: str) -> object:
        return client.post(
            "/api/vault/push",
            json={"markdown": markdown},
            headers={"Authorization": "Bearer current-token"},
        )

    def test_oversized_content_returns_400(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Content exceeding max_content_length should return 400."""
        client, _ = security_app
        big_content = "x" * 600  # > 512 bytes limit
        memory = Memory(content=big_content, category="fact", namespace="default")
        md = memory_to_markdown(memory)
        resp = self._push(client, md)
        assert resp.status_code == 400
        assert "max length" in resp.json()["error"]

    def test_valid_uuid_id_accepted(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Memory with a valid UUID id should be accepted."""
        client, _ = security_app
        import uuid
        valid_id = str(uuid.uuid4())
        memory = Memory(id=valid_id, content="ok", category="fact", namespace="default")
        md = memory_to_markdown(memory)
        resp = self._push(client, md)
        assert resp.status_code == 200

    def test_invalid_uuid_returns_400(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Memory with a UUID-shaped (36 hex+dash) but malformed id should return 400."""
        client, _ = security_app
        # 36-char string, all hex+dashes, but dashes in wrong positions (not valid UUID)
        bad_uuid = "12345678-1234-1234-1234-1234567890ab"  # valid UUID shape
        # Force wrong grouping: swap a dash position to make it structurally invalid
        # Use a string that is 36 chars, all hex+dash, but fails UUID regex
        bad_uuid = "1234567-12345-1234-1234-1234567890ab"  # 7-5-4-4-12 groups (wrong)
        memory = Memory(id=bad_uuid, content="ok", category="fact", namespace="default")
        md = memory_to_markdown(memory)
        resp = self._push(client, md)
        assert resp.status_code == 400
        assert "invalid memory ID format" in resp.json()["error"]

    def test_namespace_with_path_separator_returns_400(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Namespace containing / (path traversal) should return 400."""
        client, _ = security_app
        memory = Memory(content="test", category="fact", namespace="../evil")
        md = memory_to_markdown(memory)
        resp = self._push(client, md)
        assert resp.status_code == 400
        assert "invalid namespace" in resp.json()["error"]

    def test_namespace_with_backslash_returns_400(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Namespace containing backslash should return 400."""
        client, _ = security_app
        memory = Memory(content="test", category="fact", namespace="bad\\name")
        md = memory_to_markdown(memory)
        resp = self._push(client, md)
        assert resp.status_code == 400
        assert "invalid namespace" in resp.json()["error"]

    def test_valid_namespace_accepted(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Standard alphanumeric namespace should be accepted."""
        client, _ = security_app
        memory = Memory(content="ok", category="fact", namespace="my-namespace")
        md = memory_to_markdown(memory)
        resp = self._push(client, md)
        assert resp.status_code == 200

    def test_batch_push_validates_each_item(
        self, security_app: tuple[TestClient, SQLiteStorage]
    ) -> None:
        """Batch push should validate each item; invalid ones returned as parse_error."""
        client, _ = security_app
        valid_md = _make_valid_markdown()
        # UUID-shaped but wrong grouping (7-5-4-4-12 not 8-4-4-4-12)
        bad_id = "1234567-12345-1234-1234-1234567890ab"
        invalid_memory = Memory(id=bad_id, content="x", category="fact")
        invalid_md = memory_to_markdown(invalid_memory)

        resp = client.post(
            "/api/vault/batch-push",
            json={"files": [{"markdown": valid_md}, {"markdown": invalid_md}]},
            headers={"Authorization": "Bearer current-token"},
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert any(r.get("status") in ("created", "updated", "unchanged") for r in results)
        assert any(r.get("status") == "parse_error" for r in results)


# ---------------------------------------------------------------------------
# Audit Logging
# ---------------------------------------------------------------------------

class TestAuditLogging:
    """Vault API requests are audit-logged via VAULT_AUDIT messages."""

    def test_successful_request_is_logged(
        self,
        no_auth_app: tuple[TestClient, SQLiteStorage],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A successful vault request should emit a VAULT_AUDIT log line."""
        client, _ = no_auth_app
        md = _make_valid_markdown()
        with caplog.at_level(logging.INFO, logger="agent_memory.vault.routes"):
            client.post("/api/vault/push", json={"markdown": md})
        audit_logs = [r for r in caplog.records if "VAULT_AUDIT" in r.message]
        assert len(audit_logs) >= 1

    def test_audit_log_contains_method_and_path(
        self,
        no_auth_app: tuple[TestClient, SQLiteStorage],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Audit log should include HTTP method and path."""
        client, _ = no_auth_app
        md = _make_valid_markdown()
        with caplog.at_level(logging.INFO, logger="agent_memory.vault.routes"):
            client.post("/api/vault/push", json={"markdown": md})
        audit_logs = [r for r in caplog.records if "VAULT_AUDIT" in r.message]
        assert any("POST" in r.message and "/api/vault/push" in r.message for r in audit_logs)

    def test_audit_log_contains_status_code(
        self,
        no_auth_app: tuple[TestClient, SQLiteStorage],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Audit log should include HTTP status code."""
        client, _ = no_auth_app
        md = _make_valid_markdown()
        with caplog.at_level(logging.INFO, logger="agent_memory.vault.routes"):
            client.post("/api/vault/push", json={"markdown": md})
        audit_logs = [r for r in caplog.records if "VAULT_AUDIT" in r.message]
        assert any("200" in r.message for r in audit_logs)

    def test_health_endpoint_not_audit_logged(
        self,
        no_auth_app: tuple[TestClient, SQLiteStorage],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Health endpoint should NOT emit audit log entries."""
        client, _ = no_auth_app
        with caplog.at_level(logging.INFO, logger="agent_memory.vault.routes"):
            client.get("/health")
        audit_logs = [r for r in caplog.records if "VAULT_AUDIT" in r.message]
        assert len(audit_logs) == 0
