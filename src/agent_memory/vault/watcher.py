"""File watcher for vault folder — detects .md changes for sync."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Coroutine

logger = logging.getLogger(__name__)


async def watch_vault(
    vault_path: str,
    on_change: Callable[[str, Path], Coroutine],
) -> None:
    """Watch vault folder and trigger callback on .md changes.

    Args:
        vault_path: Root vault directory to watch.
        on_change: async callback(change_type, path) for each .md change.
            change_type is one of: "added", "modified", "deleted".
    """
    try:
        from watchfiles import Change, awatch
    except ImportError:
        logger.warning(
            "watchfiles not installed — vault file watching disabled. "
            "Install with: pip install watchfiles"
        )
        return

    change_map = {
        Change.added: "added",
        Change.modified: "modified",
        Change.deleted: "deleted",
    }

    logger.info("Watching vault folder: %s", vault_path)
    async for changes in awatch(vault_path):
        for change_type, path_str in changes:
            path = Path(path_str)
            if path.suffix != ".md":
                continue
            change_name = change_map.get(change_type, "modified")
            logger.debug("Vault file %s: %s", change_name, path)
            try:
                await on_change(change_name, path)
            except Exception:
                logger.exception("Error processing vault change: %s %s", change_name, path)
