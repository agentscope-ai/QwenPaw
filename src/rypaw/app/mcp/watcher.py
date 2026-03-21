# -*- coding: utf-8 -*-
"""Independent watcher for MCP configuration changes.

This module provides a self-contained config watcher specifically for MCP,
without coupling to the main ConfigWatcher or other components.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING, Dict

from .manager import MCPClientManager

if TYPE_CHECKING:
    from ...config.config import MCPConfig

logger = logging.getLogger(__name__)

# How often to poll (seconds)
DEFAULT_POLL_INTERVAL = 2.0


class MCPConfigWatcher:
    """Watch MCP configuration and hot-reload clients on changes.

    This is a standalone watcher that can be used independently or
    integrated with the main ConfigWatcher.
    """

    def __init__(
        self,
        mcp_manager: MCPClientManager,
        config_loader: Callable,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        config_path: Optional[Path] = None,
    ):
        """Initialize MCP config watcher.

        Args:
            mcp_manager: The MCP client manager to update
            config_loader: Function to load config, should return Config
                           object with .mcp attribute (or MCPConfig)
            poll_interval: How often to check for changes (seconds)
            config_path: Path to config file (for mtime checking)
        """
        self._mcp_manager = mcp_manager
        self._config_loader = config_loader
        self._poll_interval = poll_interval
        self._config_path = config_path
        self._task: Optional[asyncio.Task] = None

        # Snapshot of last known MCP config (for diffing)
        self._last_mcp: Optional["MCPConfig"] = None
        self._last_mcp_hash: Optional[int] = None
        # mtime of config file at last check
        self._last_mtime: float = 0.0

        # Track ongoing reload tasks to prevent blocking
        self._reload_task: Optional[asyncio.Task] = None

        # Track failed reload attempts per client to prevent infinite retries
        # Format: {client_key: (retry_count, last_config_hash)}
        self._client_failures: Dict[str, tuple[int, int]] = {}
        self._max_retries: int = 3

    async def start(self) -> None:
        """Take initial snapshot and start the polling task."""
        self._snapshot()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name="mcp_config_watcher",
        )
        logger.debug(
            "MCPConfigWatcher started (poll=%.1fs)",
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop the polling task and wait for any ongoing reload."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Wait for ongoing reload to complete
        if self._reload_task and not self._reload_task.done():
            logger.debug(
                "MCPConfigWatcher: waiting for reload task to complete",
            )
            try:
                await asyncio.wait_for(self._reload_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "MCPConfigWatcher: reload task did not finish in time",
                )
                self._reload_task.cancel()
            except Exception:
                pass

        logger.debug("MCPConfigWatcher stopped")

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _snapshot(self) -> None:
        """Load current MCP config and record mtime + hash."""
        if self._config_path:
            try:
                self._last_mtime = self._config_path.stat().st_mtime
            except FileNotFoundError:
                self._last_mtime = 0.0

        try:
            mcp_config = self._load_mcp_config()
            self._last_mcp = mcp_config.model_copy(deep=True)
            self._last_mcp_hash = self._mcp_hash(mcp_config)
        except Exception:
            logger.warning("MCPConfigWatcher: failed to load initial config")
            self._last_mcp = None
            self._last_mcp_hash = None

    def _load_mcp_config(self) -> "MCPConfig":
        """Load MCP config using the provided loader."""
        config = self._config_loader()
        # Support both Config object with .mcp or direct MCPConfig
        if hasattr(config, "mcp"):
            return config.mcp
        return config

    @staticmethod
    def _mcp_hash(mcp_config: "MCPConfig") -> int:
        """Fast hash of MCP config for quick change detection."""
        return hash(str(mcp_config.model_dump(mode="json")))

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check()
            except Exception:
                logger.exception("MCPConfigWatcher: poll iteration failed")

    async def _check(self) -> None:
        """Check for config changes and reload if needed."""
        # 1) Check mtime if config path is provided
        if self._config_path:
            try:
                mtime = self._config_path.stat().st_mtime
            except FileNotFoundError:
                return
            if mtime == self._last_mtime:
                return
            self._last_mtime = mtime

        # 2) Load new config; quick-reject if MCP section unchanged
        try:
            new_mcp = self._load_mcp_config()
        except Exception:
            logger.debug("MCPConfigWatcher: failed to parse config")
            return

        new_hash = self._mcp_hash(new_mcp)
        if new_hash == self._last_mcp_hash:
            return  # No changes

        # 3) Check if previous reload is still running
        if self._reload_task and not self._reload_task.done():
            logger.debug(
                "MCPConfigWatcher: skipping reload, "
                "previous reload still in progress",
            )
            return

        # 4) Trigger non-blocking reload in background task
        logger.debug(
            "MCPConfigWatcher: detected config changes, starting reload",
        )
        self._reload_task = asyncio.create_task(
            self._reload_changed_clients_wrapper(new_mcp),
            name="mcp_reload_task",
        )
        # Note: Snapshot is updated by the background task on success

    async def _reload_changed_clients_wrapper(
        self,
        new_mcp: "MCPConfig",
    ) -> None:
        """Wrapper for reload that handles exceptions without crashing watcher.

        Updates snapshot only on successful reload to allow retry on failure.
        Tracks failed attempts per client to prevent infinite retries.

        Args:
            new_mcp: New MCP configuration
        """
        new_hash = self._mcp_hash(new_mcp)

        try:
            await self._reload_changed_clients(new_mcp)
            # Success: update snapshot
            self._last_mcp = new_mcp.model_copy(deep=True)
            self._last_mcp_hash = new_hash
            logger.debug("MCPConfigWatcher: reload completed successfully")
        except Exception:
            logger.warning("MCPConfigWatcher: reload task failed")

    async def _reload_changed_clients(self, new_mcp: "MCPConfig") -> None:
        """Compare old and new MCP configs and reload changed clients.

        Args:
            new_mcp: New MCP configuration
        """
        old_mcp = self._last_mcp
        old_clients = old_mcp.clients if old_mcp else {}

        # Check for new or changed clients
        for key, new_cfg in new_mcp.clients.items():
            old_cfg = old_clients.get(key)
            await self._handle_client_update(key, old_cfg, new_cfg)

        # Remove clients that no longer exist in config
        for key in old_clients:
            if key not in new_mcp.clients:
                await self._handle_client_removal(key)

    async def _handle_client_update(
        self,
        key: str,
        old_cfg,
        new_cfg,
    ) -> None:
        """Handle update for a single client."""
        # Client disabled: remove if it was previously enabled
        if not new_cfg.enabled:
            if old_cfg and old_cfg.enabled:
                logger.debug(
                    "MCPConfigWatcher: client '%s' disabled, removing",
                    key,
                )
                try:
                    await self._mcp_manager.remove_client(key)
                    self._client_failures.pop(key, None)
                except Exception:
                    logger.debug(
                        "MCPConfigWatcher: failed to remove client '%s'",
                        key,
                    )
            return

        # Client enabled: check if config changed
        if old_cfg != new_cfg:
            await self._reload_single_client(key, new_cfg)

    async def _reload_single_client(self, key: str, new_cfg) -> None:
        """Reload a single client with retry tracking."""
        client_hash = hash(str(new_cfg.model_dump(mode="json")))

        # Check if this client should be skipped
        if self._should_skip_client(key, client_hash):
            return

        logger.debug(
            "MCPConfigWatcher: client '%s' config changed, reloading",
            key,
        )
        try:
            await self._mcp_manager.replace_client(key, new_cfg)
            logger.debug(
                "MCPConfigWatcher: client '%s' reloaded successfully",
                key,
            )
            self._client_failures.pop(key, None)
        except Exception:
            self._track_client_failure(key, client_hash)

    def _should_skip_client(self, key: str, client_hash: int) -> bool:
        """Check if client should be skipped due to failures."""
        if key in self._client_failures:
            retry_count, last_hash = self._client_failures[key]
            if last_hash == client_hash and retry_count >= self._max_retries:
                logger.debug(
                    f"MCPConfigWatcher: skipping client '{key}', "
                    f"failed {retry_count} times. "
                    f"Modify config to retry.",
                )
                return True
        return False

    def _track_client_failure(self, key: str, client_hash: int) -> None:
        """Track failure for a specific client."""
        if key in self._client_failures:
            old_count, old_hash = self._client_failures[key]
            new_count = old_count + 1 if old_hash == client_hash else 1
        else:
            new_count = 1

        self._client_failures[key] = (new_count, client_hash)

        if new_count >= self._max_retries:
            logger.warning(
                f"MCPConfigWatcher: client '{key}' failed "
                f"{new_count} times, giving up. "
                f"Fix config and modify to retry.",
            )
        else:
            logger.debug(
                f"MCPConfigWatcher: failed to reload "
                f"client '{key}' "
                f"(attempt {new_count}/{self._max_retries})",
            )

    async def _handle_client_removal(self, key: str) -> None:
        """Handle removal of a client from config."""
        logger.debug(
            "MCPConfigWatcher: client '%s' removed from config",
            key,
        )
        try:
            await self._mcp_manager.remove_client(key)
            self._client_failures.pop(key, None)
        except Exception:
            logger.debug(
                "MCPConfigWatcher: failed to remove client '%s'",
                key,
            )
