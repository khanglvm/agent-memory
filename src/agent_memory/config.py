"""Configuration system — YAML file + env var overrides."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class StorageConfig(BaseModel):
    """SQLite storage configuration."""

    db_path: str = Field(
        default="~/.agent-memory/memory.db",
        description="Path to SQLite database file",
    )

    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()


class EmbeddingConfig(BaseModel):
    """Embedding provider configuration."""

    provider: str | None = Field(default=None, description="openai | ollama | none")
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: str | None = Field(default=None, description="API key (use env vars)")
    model: str = Field(default="text-embedding-3-small")
    dimensions: int = Field(default=1536)
    allow_insecure: bool = Field(
        default=False,
        description="Allow HTTP when api_key is set (not recommended)",
    )


class ConsolidationConfig(BaseModel):
    """LLM consolidation configuration."""

    provider: str | None = Field(default=None, description="openai | ollama | none")
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: str | None = Field(default=None, description="API key (use env vars)")
    model: str = Field(default="gpt-4o-mini")
    allow_insecure: bool = Field(
        default=False,
        description="Allow HTTP when api_key is set (not recommended)",
    )
    auto_interval_minutes: int = Field(
        default=0, description="0 = disabled, >0 = auto-consolidate"
    )
    min_memories: int = Field(default=3, description="Minimum unconsolidated to trigger")
    prompt_template: str | None = Field(default=None, description="Custom prompt path")


class ServerConfig(BaseModel):
    """MCP server configuration."""

    transport: str = Field(default="stdio", description="stdio | http")
    http_host: str = Field(default="127.0.0.1")
    http_port: int = Field(default=8888)
    auth_token: str | None = Field(default=None, description="Bearer token for HTTP")
    auth_token_previous: str | None = Field(
        default=None, description="Previous auth token accepted during rotation"
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:*"])
    tls_cert: str | None = Field(default=None, description="Path to TLS certificate")
    tls_key: str | None = Field(default=None, description="Path to TLS private key")


class IngestionConfig(BaseModel):
    """File ingestion configuration."""

    allowed_paths: list[str] = Field(
        default_factory=list,
        description="Allowed directories for ingest_file (empty = disabled)",
    )
    max_file_size_mb: float = Field(default=1.0)
    supported_extensions: list[str] = Field(
        default_factory=lambda: [".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".xml", ".log"]
    )


class VaultConfig(BaseModel):
    """Obsidian vault sync configuration."""

    enabled: bool = Field(default=False)
    vault_path: str | None = Field(
        default=None, description="Obsidian vault path for .md sync"
    )
    sync_folder: str = Field(
        default="memory-vault", description="Subfolder within vault"
    )
    watch_local: bool = Field(
        default=False,
        description="Watch vault folder for direct edits (Mac Mini only)",
    )
    write_on_store: bool = Field(
        default=True,
        description="Auto-write .md when memory stored via MCP",
    )
    api_port: int = Field(default=8889, description="Vault REST API port")
    rate_limit_max: int = Field(default=100, description="Max requests per window")
    rate_limit_window_sec: int = Field(default=60, description="Rate limit window in seconds")
    max_content_length: int = Field(
        default=10240, description="Max content length per memory (bytes)"
    )


class MemoryConfig(BaseModel):
    """Root configuration model."""

    storage: StorageConfig = Field(default_factory=StorageConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    consolidation: ConsolidationConfig = Field(default_factory=ConsolidationConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    vault: VaultConfig = Field(default_factory=VaultConfig)
    log_level: str = Field(default="INFO")


ENV_PREFIX = "AGENT_MEMORY_"

# Pattern to match ${VAR_NAME} for env var substitution in YAML values
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} with environment variable values."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _walk_and_substitute(data: dict | list | str) -> dict | list | str:
    """Recursively substitute env vars in YAML data."""
    if isinstance(data, dict):
        return {k: _walk_and_substitute(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_walk_and_substitute(item) for item in data]
    if isinstance(data, str):
        return _substitute_env_vars(data)
    return data


def _apply_env_overrides(data: dict) -> dict:
    """Apply AGENT_MEMORY_* env var overrides.

    Mapping: AGENT_MEMORY_STORAGE__DB_PATH -> storage.db_path
    """
    for key, value in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        parts = key[len(ENV_PREFIX) :].lower().split("__")
        target = data
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return data


def load_config(config_path: str | Path | None = None) -> MemoryConfig:
    """Load configuration from YAML file + env var overrides.

    Priority: defaults < YAML file < env vars
    """
    data: dict = {}

    # Resolve config path from arg, env var, or default
    if config_path is None:
        config_path = os.environ.get("AGENT_MEMORY_CONFIG")

    if config_path is not None:
        path = Path(config_path).expanduser()
        if path.exists():
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            data = _walk_and_substitute(raw)

    data = _apply_env_overrides(data)

    return MemoryConfig.model_validate(data)
