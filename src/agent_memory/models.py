"""Data models for agent memory system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class Memory(BaseModel):
    """A single memory unit."""

    id: str = Field(default_factory=_new_id)
    namespace: str = Field(default="default")
    content: str
    summary: str | None = None
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    category: str = Field(default="fact")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    connections: list[str] = Field(default_factory=list)
    consolidated: bool = Field(default=False)
    source: str = Field(default="mcp", description="Origin: mcp | obsidian | mobile")
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


class MemorySearchResult(BaseModel):
    """Memory with similarity score from vector search."""

    memory: Memory
    similarity: float = Field(default=0.0)


class Consolidation(BaseModel):
    """Result of consolidation across multiple memories."""

    id: str = Field(default_factory=_new_id)
    namespace: str = Field(default="default")
    source_ids: list[str] = Field(default_factory=list)
    summary: str
    insight: str
    created_at: str = Field(default_factory=_utc_now)


class Namespace(BaseModel):
    """A memory namespace."""

    name: str
    description: str = ""
    created_at: str = Field(default_factory=_utc_now)
