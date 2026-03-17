"""Bidirectional Memory <-> Markdown serializer with YAML frontmatter."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import yaml

from agent_memory.models import Memory


def memory_to_markdown(memory: Memory) -> str:
    """Render Memory as .md with YAML frontmatter."""
    frontmatter: dict[str, Any] = {
        "id": memory.id,
        "namespace": memory.namespace,
        "category": memory.category,
        "importance": memory.importance,
        "source": memory.source,
        "consolidated": memory.consolidated,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
    }
    if memory.summary:
        frontmatter["summary"] = memory.summary
    if memory.entities:
        frontmatter["entities"] = memory.entities
    if memory.topics:
        frontmatter["topics"] = memory.topics
    if memory.connections:
        frontmatter["connections"] = memory.connections

    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    return f"---\n{fm_str}---\n\n{memory.content}\n"


def markdown_to_memory(text: str) -> Memory:
    """Parse .md with YAML frontmatter into Memory."""
    text = text.strip()
    if not text.startswith("---"):
        raise ValueError("Missing YAML frontmatter delimiter")

    # Split on the second ---
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Incomplete YAML frontmatter")

    fm_raw = parts[1].strip()
    content = parts[2].strip()

    if not fm_raw:
        raise ValueError("Empty YAML frontmatter")

    data = yaml.safe_load(fm_raw)
    if not isinstance(data, dict):
        raise ValueError("YAML frontmatter must be a mapping")

    return Memory(
        id=data.get("id", None),
        namespace=data.get("namespace", "default"),
        content=content,
        summary=data.get("summary"),
        entities=data.get("entities", []),
        topics=data.get("topics", []),
        category=data.get("category", "fact"),
        importance=data.get("importance", 0.5),
        connections=data.get("connections", []),
        consolidated=data.get("consolidated", False),
        source=data.get("source", "obsidian"),
        created_at=data.get("created_at", None),
        updated_at=data.get("updated_at", None),
    )


def content_to_slug(content: str, max_length: int = 50) -> str:
    """Generate kebab-case slug from content's first line or title."""
    first_line = content.strip().split("\n")[0].strip("# ").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", first_line.lower()).strip("-")
    return slug[:max_length] if slug else "untitled"


def unique_slug(slug: str, existing_slugs: set[str], disambiguator: str = "") -> str:
    """Append short hash if slug collides. Uses disambiguator (e.g. memory ID) for uniqueness."""
    if slug not in existing_slugs:
        return slug
    # Hash the disambiguator (or slug+timestamp as fallback) to ensure uniqueness
    seed = disambiguator or f"{slug}-{hashlib.sha256(slug.encode()).hexdigest()}"
    short_hash = hashlib.sha256(seed.encode()).hexdigest()[:6]
    return f"{slug}-{short_hash}"


def memory_to_filename(memory: Memory) -> str:
    """Generate filename: {category}-{slug}.md"""
    slug = content_to_slug(memory.content)
    return f"{memory.category}-{slug}.md"
