"""Tests for configuration loading and environment variable handling."""

from __future__ import annotations

from pathlib import Path

from agent_memory.config import (
    EmbeddingConfig,
    MemoryConfig,
    StorageConfig,
    load_config,
)


class TestStorageConfig:
    """Tests for StorageConfig."""

    def test_default_storage_config(self) -> None:
        """Test default storage configuration."""
        config = StorageConfig()
        assert config.db_path == "~/.agent-memory/memory.db"

    def test_custom_db_path(self) -> None:
        """Test custom database path."""
        config = StorageConfig(db_path="/tmp/test.db")
        assert config.db_path == "/tmp/test.db"

    def test_resolved_db_path_expansion(self) -> None:
        """Test that ~ is expanded in resolved_db_path."""
        config = StorageConfig(db_path="~/test.db")
        resolved = config.resolved_db_path()
        assert "~" not in str(resolved)
        assert resolved.is_absolute()


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig."""

    def test_default_embedding_config(self) -> None:
        """Test default embedding configuration."""
        config = EmbeddingConfig()
        assert config.provider is None
        assert config.base_url == "https://api.openai.com/v1"
        assert config.model == "text-embedding-3-small"
        assert config.dimensions == 1536

    def test_custom_embedding_config(self) -> None:
        """Test custom embedding configuration."""
        config = EmbeddingConfig(
            provider="openai",
            api_key="test-key",
            model="text-embedding-3-large",
            dimensions=3072,
        )
        assert config.provider == "openai"
        assert config.api_key == "test-key"
        assert config.model == "text-embedding-3-large"
        assert config.dimensions == 3072


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_defaults(self) -> None:
        """Test loading config with no file (defaults only)."""
        config = load_config(None)
        assert isinstance(config, MemoryConfig)
        assert config.storage.db_path == "~/.agent-memory/memory.db"
        assert config.embedding.provider is None
        assert config.log_level == "INFO"

    def test_load_config_from_yaml(self, tmp_path: Path) -> None:
        """Test loading config from YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
storage:
  db_path: /custom/path.db
embedding:
  provider: openai
  api_key: test-key
consolidation:
  min_memories: 5
log_level: DEBUG
""")
        config = load_config(config_file)
        assert config.storage.db_path == "/custom/path.db"
        assert config.embedding.provider == "openai"
        assert config.embedding.api_key == "test-key"
        assert config.consolidation.min_memories == 5
        assert config.log_level == "DEBUG"

    def test_load_config_yaml_with_env_substitution(self, tmp_path: Path, monkeypatch) -> None:
        """Test ${VAR_NAME} substitution in YAML."""
        monkeypatch.setenv("DB_PATH", "/home/user/memory.db")
        monkeypatch.setenv("API_KEY", "secret-key-123")

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
storage:
  db_path: ${DB_PATH}
embedding:
  api_key: ${API_KEY}
""")
        config = load_config(config_file)
        assert config.storage.db_path == "/home/user/memory.db"
        assert config.embedding.api_key == "secret-key-123"

    def test_load_config_env_var_overrides(self, tmp_path: Path, monkeypatch) -> None:
        """Test AGENT_MEMORY_* environment variable overrides."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
storage:
  db_path: /original/path.db
embedding:
  provider: openai
""")

        monkeypatch.setenv("AGENT_MEMORY_STORAGE__DB_PATH", "/overridden/path.db")
        monkeypatch.setenv("AGENT_MEMORY_EMBEDDING__PROVIDER", "ollama")
        monkeypatch.setenv("AGENT_MEMORY_LOG_LEVEL", "WARNING")

        config = load_config(config_file)
        assert config.storage.db_path == "/overridden/path.db"
        assert config.embedding.provider == "ollama"
        assert config.log_level == "WARNING"

    def test_load_config_env_var_takes_precedence(self, monkeypatch) -> None:
        """Test that env vars override YAML which overrides defaults."""
        monkeypatch.setenv("AGENT_MEMORY_LOG_LEVEL", "ERROR")
        config = load_config(None)
        assert config.log_level == "ERROR"

    def test_load_config_from_env_path(self, tmp_path: Path, monkeypatch) -> None:
        """Test loading config via AGENT_MEMORY_CONFIG env var."""
        config_file = tmp_path / "custom_config.yaml"
        config_file.write_text("log_level: CRITICAL")

        monkeypatch.setenv("AGENT_MEMORY_CONFIG", str(config_file))
        config = load_config()
        assert config.log_level == "CRITICAL"

    def test_load_config_nonexistent_file_uses_defaults(self) -> None:
        """Test that nonexistent YAML file falls back to defaults."""
        config = load_config("/nonexistent/path/config.yaml")
        assert config.log_level == "INFO"
        assert config.storage.db_path == "~/.agent-memory/memory.db"

    def test_load_config_ingestion_allowed_paths(self, tmp_path: Path) -> None:
        """Test ingestion allowed_paths configuration."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
ingestion:
  allowed_paths:
    - /home/user/documents
    - /tmp
  max_file_size_mb: 5.0
""")
        config = load_config(config_file)
        assert config.ingestion.allowed_paths == ["/home/user/documents", "/tmp"]
        assert config.ingestion.max_file_size_mb == 5.0

    def test_load_config_server_settings(self, tmp_path: Path) -> None:
        """Test server configuration."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
server:
  transport: http
  http_host: 0.0.0.0
  http_port: 9000
  auth_token: my-secret-token
""")
        config = load_config(config_file)
        assert config.server.transport == "http"
        assert config.server.http_host == "0.0.0.0"
        assert config.server.http_port == 9000
        assert config.server.auth_token == "my-secret-token"
