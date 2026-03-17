"""Vault file writer — writes Memory objects as .md files to vault folder."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agent_memory.vault.serializer import (
    content_to_slug,
    memory_to_markdown,
    unique_slug,
)

if TYPE_CHECKING:
    from agent_memory.config import VaultConfig
    from agent_memory.models import Memory

logger = logging.getLogger(__name__)


def _sanitize_path_component(name: str) -> str:
    """Sanitize a path component to prevent traversal."""
    # Remove path separators and dangerous chars
    sanitized = re.sub(r"[/\\.\x00]", "-", name).strip("-")
    return sanitized or "default"


async def write_memory_to_vault(memory: Memory, config: VaultConfig) -> Path:
    """Write Memory as .md to vault folder.

    Returns the path of the written file.
    """
    if not config.vault_path:
        raise ValueError("vault_path not configured")

    vault_root = Path(config.vault_path).expanduser() / config.sync_folder
    vault_root = vault_root.resolve()

    # Sanitize namespace and category to prevent path traversal
    safe_namespace = _sanitize_path_component(memory.namespace)
    safe_category = _sanitize_path_component(memory.category)

    vault_dir = vault_root / safe_namespace
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Verify directory is within vault root
    if not vault_dir.resolve().is_relative_to(vault_root):
        raise ValueError(f"Path traversal detected: namespace={memory.namespace!r}")

    slug = content_to_slug(memory.content)
    existing_slugs = {f.stem for f in vault_dir.iterdir() if f.suffix == ".md"}

    # Check if this memory already has a file (by ID in frontmatter)
    existing_path = await asyncio.to_thread(_find_existing_file, vault_dir, memory.id)
    if existing_path:
        file_path = existing_path
    else:
        full_slug = f"{safe_category}-{unique_slug(slug, existing_slugs)}"
        file_path = vault_dir / f"{full_slug}.md"

    # Final safety check
    if not file_path.resolve().is_relative_to(vault_root):
        raise ValueError("Path traversal detected in generated filename")

    content = memory_to_markdown(memory)
    await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")

    logger.debug("Wrote vault file: %s", file_path)
    return file_path


def _find_existing_file(vault_dir: Path, memory_id: str) -> Path | None:
    """Find existing .md file for a memory by scanning frontmatter for matching ID."""
    # Use exact YAML key match pattern
    marker = f"\nid: {memory_id}\n"
    for md_file in vault_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            # Only search within frontmatter (between first pair of ---)
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    frontmatter = text[3:end]
                    if marker in f"\n{frontmatter}\n":
                        return md_file
        except OSError:
            continue
    return None
