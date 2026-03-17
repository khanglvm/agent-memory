"""Text and file ingestion processor for agent memory."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_memory.config import IngestionConfig
    from agent_memory.embedding.base import EmbeddingProvider
    from agent_memory.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Extract from this content:
1. A 1-2 sentence summary
2. Key entities (people, companies, concepts)
3. 2-4 topic tags
4. Importance (0.0-1.0)
Return ONLY valid JSON: {"summary": "...", "entities": [...], "topics": [...], "importance": 0.5}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_BRACE_RE = re.compile(r"\{[\s\S]*\}")


def _parse_llm_json(raw: str) -> dict | None:
    """Multi-layer JSON parsing: direct -> markdown fence -> first brace block."""
    # Layer 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Layer 2: markdown code fence
    match = _FENCE_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Layer 3: first {...} block
    match = _BRACE_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


class IngestionProcessor:
    """Processes text and file ingestion into the memory store."""

    def __init__(
        self,
        storage: SQLiteStorage,
        embedding_provider: EmbeddingProvider,
        llm_provider: object | None,
        config: IngestionConfig,
    ) -> None:
        self._storage = storage
        self._embedding_provider = embedding_provider
        self._llm = llm_provider
        self._config = config

    async def ingest_text(self, text: str, source: str, namespace: str) -> str:
        """Ingest raw text as a memory, optionally enriched via LLM.

        Returns the stored memory_id.
        """
        from agent_memory.models import Memory

        summary: str | None = None
        entities: list[str] = []
        topics: list[str] = []
        importance: float = 0.5

        if self._llm is not None:
            try:
                raw = await self._llm.generate(  # type: ignore[union-attr]
                    f"Source: {source}\n\nContent:\n{text}",
                    system=_EXTRACTION_PROMPT,
                )
                parsed = _parse_llm_json(raw)
                if parsed is not None:
                    summary = parsed.get("summary") or None
                    entities = parsed.get("entities") or []
                    topics = parsed.get("topics") or []
                    raw_imp = parsed.get("importance", 0.5)
                    importance = max(0.0, min(1.0, float(raw_imp)))
                else:
                    logger.warning("LLM extraction returned unparseable output; using raw storage")
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM extraction failed: %s; using raw storage", exc)

        memory = Memory(
            namespace=namespace,
            content=text,
            summary=summary,
            entities=entities,
            topics=topics,
            importance=importance,
            category="fact",
        )

        embedding: list[float] | None = None
        if self._embedding_provider.dimensions > 0:
            try:
                embedding = await self._embedding_provider.embed(text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding generation failed: %s", exc)

        return await self._storage.store(memory, embedding=embedding)

    async def ingest_file(self, file_path: str, namespace: str) -> str:
        """Ingest a file as a memory with deduplication and path validation.

        Returns the stored memory_id.
        Raises ValueError for invalid paths, unsupported extensions, or oversized files.
        Raises FileNotFoundError if the file does not exist.
        """
        path = self._validate_path(Path(file_path))

        # Extension check
        if path.suffix.lower() not in self._config.supported_extensions:
            raise ValueError(
                f"Unsupported file extension {path.suffix!r}. "
                f"Allowed: {self._config.supported_extensions}"
            )

        # Size check
        size_bytes = path.stat().st_size
        max_bytes = self._config.max_file_size_mb * 1024 * 1024
        if size_bytes > max_bytes:
            raise ValueError(
                f"File size {size_bytes / (1024 * 1024):.2f} MB exceeds "
                f"limit of {self._config.max_file_size_mb} MB"
            )

        # Read content and compute hash
        content = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Dedup check
        already_processed = await self._storage.check_file_processed(str(path))
        if already_processed:
            logger.info("File already processed (dedup): %s", path)
            # Return a stable indicator; caller receives the original memory_id is unknown,
            # so we re-ingest and let the storage layer handle idempotency naturally.
            # However the spec says "check content hash for dedup" — skip re-ingest.
            raise ValueError(f"File already ingested (path={path})")

        memory_id = await self.ingest_text(content, source=str(path), namespace=namespace)

        await self._storage.mark_file_processed(str(path), namespace, content_hash)

        return memory_id

    def _validate_path(self, path: Path) -> Path:
        """Resolve symlinks and verify path is within an allowed directory.

        Raises ValueError if allowed_paths is empty (feature disabled) or if
        the resolved path is outside all allowed paths.
        """
        if not self._config.allowed_paths:
            raise ValueError(
                "ingest_file is disabled: no allowed_paths configured. "
                "Add at least one directory to ingestion.allowed_paths in config."
            )

        resolved = path.resolve()

        for allowed in self._config.allowed_paths:
            allowed_resolved = Path(allowed).expanduser().resolve()
            try:
                resolved.relative_to(allowed_resolved)
                return resolved
            except ValueError:
                continue

        raise ValueError(
            f"Path {path!r} is outside all allowed directories: {self._config.allowed_paths}"
        )
