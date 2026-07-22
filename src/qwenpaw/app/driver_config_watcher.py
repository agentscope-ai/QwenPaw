# -*- coding: utf-8 -*-
"""Watch DriverCard files and hot-reload active Drivers.

This is the protocol-neutral successor to the old MCP-only config watcher.
Console/API saves already apply runtime updates directly. This watcher
preserves the manual-edit path for ``drivers/<protocol>/<name>.yaml`` files.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ..drivers.storage import AsyncDriverCardStore

if TYPE_CHECKING:
    from ..drivers.manager import DriverManager

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 2.0


class DriverConfigWatcher:
    """Poll DriverCard storage and refresh changed external capabilities."""

    def __init__(
        self,
        driver_manager: "DriverManager",
        cards_dir: Path,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._driver_manager = driver_manager
        self._card_store: AsyncDriverCardStore = driver_manager.card_store
        self._cards_dir = cards_dir
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._last_snapshot: dict[str, tuple[str, float]] = {}

    async def start(self) -> None:
        """Take an initial snapshot and start the polling task."""
        self._last_snapshot = await self._card_store.snapshot()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name="driver_config_watcher",
        )
        logger.info(
            "DriverConfigWatcher started (poll=%.1fs, path=%s)",
            self._poll_interval,
            self._cards_dir,
        )

    async def stop(self) -> None:
        """Stop the polling task."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("DriverConfigWatcher stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check_once()
            except Exception:
                logger.warning(
                    "DriverConfigWatcher poll iteration failed",
                    exc_info=True,
                )

    async def _check_once(self) -> None:
        current = await self._card_store.snapshot()
        if current == self._last_snapshot:
            return

        old = self._last_snapshot

        removed_paths = sorted(set(old) - set(current))
        changed_paths = sorted(
            path_id
            for path_id, state in current.items()
            if old.get(path_id) != state
        )
        current_names = {state[0] for state in current.values()}
        removed_names = {
            old[path_id][0]
            for path_id in removed_paths
            if old[path_id][0] not in current_names
        }
        changed_names = {current[path_id][0] for path_id in changed_paths}
        changed_names.update(
            old[path_id][0]
            for path_id in removed_paths
            if old[path_id][0] in current_names
        )

        for name in sorted(removed_names):
            try:
                await self._driver_manager.delete_driver(name)
                logger.info("Driver '%s' removed after card deletion", name)
            except Exception:
                logger.warning(
                    "Failed to remove Driver '%s' after card deletion",
                    name,
                    exc_info=True,
                )

        for name in sorted(changed_names):
            try:
                await self._driver_manager.refresh_driver(name)
                logger.info("Driver '%s' refreshed after card change", name)
            except Exception:
                logger.warning(
                    "Failed to refresh Driver '%s' after card change",
                    name,
                    exc_info=True,
                )

        # Use the snapshot that triggered this pass as the baseline. If a
        # manual edit lands while refresh_driver() is running, the next poll
        # will compare against this observed state and apply it instead of
        # accidentally swallowing the newer write.
        self._last_snapshot = current
