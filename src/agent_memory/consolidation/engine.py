"""Consolidation engine — orchestrates LLM calls, parsing, and storage. [RT-5/6/7]"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from pydantic import ValidationError

from agent_memory.config import ConsolidationConfig
from agent_memory.consolidation.llm import LLMProvider
from agent_memory.consolidation.prompts import (
    CONSOLIDATION_SYSTEM,
    ConsolidationResponse,
    build_consolidation_prompt,
)
from agent_memory.models import Consolidation
from agent_memory.storage.sqlite import SQLiteStorage

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_CIRCUIT_BREAKER_THRESHOLD = 3

# Regex to grab first complete {...} JSON block from LLM output
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.DOTALL)


def _parse_llm_json(raw: str) -> ConsolidationResponse:
    """Multi-layer JSON parsing [RT-7]:
    1. json.loads on the raw string
    2. Extract from ```json ... ``` markdown fences
    3. Regex first {...} block
    4. Pydantic validation on every successful parse
    """
    attempts: list[str] = [raw]

    # Layer 2: strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence_match:
        attempts.append(fence_match.group(1).strip())

    # Layer 3: first {...} block
    block_match = _JSON_BLOCK_RE.search(raw)
    if block_match:
        attempts.append(block_match.group(0))

    last_exc: Exception = ValueError("No parseable JSON found")
    for candidate in attempts:
        try:
            data = json.loads(candidate)
            return ConsolidationResponse.model_validate(data)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_exc = exc

    raise ValueError(f"Failed to parse LLM response: {last_exc}") from last_exc


class ConsolidationEngine:
    """Orchestrates memory consolidation via an LLM provider.

    - Per-namespace asyncio locks prevent concurrent consolidations. [RT-6]
    - Transactional: memories only marked consolidated after successful store. [RT-5]
    - Multi-layer JSON parsing with up to 3 retries per attempt. [RT-7]
    - Circuit breaker disables auto-consolidation after 3 consecutive batch failures.
    """

    def __init__(
        self,
        storage: SQLiteStorage,
        llm_provider: LLMProvider,
        config: ConsolidationConfig,
    ) -> None:
        self._storage = storage
        self.llm_provider = llm_provider  # exposed for __main__.py
        self._config = config
        self._locks: dict[str, asyncio.Lock] = {}  # [RT-6]
        self._consecutive_failures = 0

    def _get_lock(self, namespace: str) -> asyncio.Lock:
        """Return (creating if needed) the per-namespace lock. [RT-6]"""
        if namespace not in self._locks:
            self._locks[namespace] = asyncio.Lock()
        return self._locks[namespace]

    async def consolidate(self, namespace: str) -> Consolidation:
        """Run one consolidation pass for the given namespace.

        Raises ValueError if there are not enough unconsolidated memories.
        """
        lock = self._get_lock(namespace)
        async with lock:
            return await self._run_consolidation(namespace)

    async def _run_consolidation(self, namespace: str) -> Consolidation:
        memories = await self._storage.get_unconsolidated(
            namespace, limit=self._config.min_memories * 10
        )

        if len(memories) < self._config.min_memories:
            raise ValueError(
                f"Not enough unconsolidated memories in '{namespace}': "
                f"need {self._config.min_memories}, have {len(memories)}"
            )

        prompt = build_consolidation_prompt(memories)
        last_exc: Exception = RuntimeError("Consolidation failed")

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                raw = await self.llm_provider.generate(
                    prompt=prompt, system=CONSOLIDATION_SYSTEM
                )
                parsed = _parse_llm_json(raw)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Consolidation parse attempt %d/%d failed: %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
        else:
            raise ValueError(
                f"Consolidation failed after {_MAX_RETRIES} attempts"
            ) from last_exc

        if parsed.duplicate_candidates:
            logger.info(
                "Duplicate candidates flagged (not deleted): %s",
                parsed.duplicate_candidates,
            )

        consolidation = Consolidation(
            namespace=namespace,
            source_ids=[m.id for m in memories],
            summary=parsed.summary,
            insight=parsed.insight,
        )

        # [RT-5] Atomic: store_consolidation marks memories consolidated inside one txn
        await self._storage.store_consolidation(consolidation)

        self._consecutive_failures = 0
        logger.info(
            "Consolidation complete for '%s': %d memories -> 1 insight",
            namespace,
            len(memories),
        )
        return consolidation

    async def start_auto_consolidation(self) -> None:
        """Background loop that consolidates on a fixed interval.

        Skips if the namespace lock is already held (manual consolidation running).
        Disables itself after _CIRCUIT_BREAKER_THRESHOLD consecutive failures.
        """
        interval_seconds = self._config.auto_interval_minutes * 60
        if interval_seconds <= 0:
            return

        namespace = "default"
        logger.info(
            "Auto-consolidation enabled: interval=%dm, min_memories=%d",
            self._config.auto_interval_minutes,
            self._config.min_memories,
        )

        while True:
            await asyncio.sleep(interval_seconds)

            if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                logger.error(
                    "Auto-consolidation circuit breaker tripped after %d consecutive "
                    "failures — disabled. Restart server to re-enable.",
                    self._consecutive_failures,
                )
                return

            lock = self._get_lock(namespace)
            if lock.locked():
                logger.debug("Auto-consolidation skipped: namespace lock held")
                continue

            memories = await self._storage.get_unconsolidated(namespace, limit=1)
            if len(memories) < self._config.min_memories:
                logger.debug(
                    "Auto-consolidation skipped: %d < %d memories",
                    len(memories),
                    self._config.min_memories,
                )
                continue

            try:
                async with lock:
                    await self._run_consolidation(namespace)
                self._consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                logger.warning(
                    "Auto-consolidation failed (%d/%d): %s",
                    self._consecutive_failures,
                    _CIRCUIT_BREAKER_THRESHOLD,
                    exc,
                )
