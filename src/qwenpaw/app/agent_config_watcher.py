# -*- coding: utf-8 -*-
"""Watch agent.json and trigger a graceful workspace reload on change.

Delegates to ``MultiAgentManager.reload_agent`` so disk-edit reloads
go through the same atomic workspace swap as frontend saves and wait
for in-flight tasks. Only triggers when ``channels`` or ``heartbeat``
hashes change, so runtime bookkeeping rewrites (e.g. ``last_dispatch``)
do not cause spurious reloads.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from ..config.config import load_agent_config

if TYPE_CHECKING:
    from ..config.config import HeartbeatConfig
    from .workspace.workspace import Workspace

logger = logging.getLogger(__name__)

# How often to poll (seconds)
DEFAULT_POLL_INTERVAL = 2.0


def _channels_hash(channels: Any) -> Optional[int]:
    """Hash of channels section for change detection."""
    if channels is None:
        return None
    return hash(str(channels.model_dump(mode="json")))


def _heartbeat_hash(hb: Optional["HeartbeatConfig"]) -> int:
    """Hash of heartbeat config for change detection."""
    if hb is None:
        return hash("None")
    return hash(str(hb.model_dump(mode="json")))


class AgentConfigWatcher:
    """Poll ``agent.json`` and trigger a graceful workspace reload."""

    def __init__(
        self,
        agent_id: str,
        workspace_dir: Path,
        workspace: "Workspace",
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        """Initialize agent config watcher.

        Args:
            agent_id: Agent ID to monitor.
            workspace_dir: Path to agent's workspace directory.
            workspace: Owning ``Workspace`` instance. The manager is
                resolved lazily from it, since ``set_manager`` runs
                after ``Workspace.start()``.
            poll_interval: How often to check for changes (seconds).
        """
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._config_path = workspace_dir / "agent.json"
        self._workspace = workspace
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None

        self._last_mtime: float = 0.0
        self._last_channels_hash: Optional[int] = None
        self._last_heartbeat_hash: Optional[int] = None

        # Set before triggering reload; poll loop checks this to stop.
        self._disabled: bool = False

    async def start(self) -> None:
        """Take initial snapshot and start the polling task."""
        self._snapshot()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"agent_config_watcher_{self._agent_id}",
        )
        logger.info(
            f"AgentConfigWatcher started for agent {self._agent_id} "
            f"(poll={self._poll_interval}s, path={self._config_path})",
        )

    async def stop(self) -> None:
        """Stop the polling task (no-op if already disabled)."""
        if self._disabled:
            logger.info(
                f"AgentConfigWatcher already disabled for agent "
                f"{self._agent_id}, skipping cancel",
            )
            return
        self._disabled = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"AgentConfigWatcher stopped for agent {self._agent_id}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_mtime(self) -> float:
        """Return current mtime of agent.json, 0.0 if missing."""
        try:
            return self._config_path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _snapshot(self) -> None:
        """Record current mtime and section hashes as the new baseline."""
        self._last_mtime = self._read_mtime()
        try:
            agent_config = load_agent_config(self._agent_id)
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"failed to load initial config",
            )
            return
        self._last_channels_hash = _channels_hash(
            getattr(agent_config, "channels", None),
        )
        self._last_heartbeat_hash = _heartbeat_hash(
            getattr(agent_config, "heartbeat", None),
        )

    def _resolve_manager(self):
        """Return ``MultiAgentManager`` from the workspace, or ``None``."""
        # pylint: disable=protected-access
        return getattr(self._workspace, "_manager", None)

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while not self._disabled:
            try:
                await asyncio.sleep(self._poll_interval)
                if self._disabled:
                    break
                await self._check()
            except Exception:
                logger.exception(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"poll iteration failed",
                )

    async def _check(self) -> None:
        """Check for meaningful config changes and trigger a reload."""
        mtime = self._read_mtime()
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        try:
            agent_config = load_agent_config(self._agent_id)
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"failed to parse agent.json",
            )
            return

        new_channels_hash = _channels_hash(
            getattr(agent_config, "channels", None),
        )
        new_heartbeat_hash = _heartbeat_hash(
            getattr(agent_config, "heartbeat", None),
        )

        old_channels_hash = self._last_channels_hash
        old_heartbeat_hash = self._last_heartbeat_hash

        changed = (
            new_channels_hash != old_channels_hash
            or new_heartbeat_hash != old_heartbeat_hash
        )

        # Refresh hashes regardless so non-meaningful rewrites
        # (e.g. last_dispatch) re-baseline silently.
        self._last_channels_hash = new_channels_hash
        self._last_heartbeat_hash = new_heartbeat_hash

        if not changed:
            return

        manager = self._resolve_manager()
        if manager is None:
            logger.warning(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"config changed but MultiAgentManager not attached; "
                f"skipping reload",
            )
            return

        self._disabled = True

        logger.info(
            f"AgentConfigWatcher ({self._agent_id}): "
            f"config changed, triggering graceful reload "
            f"(channels: {old_channels_hash} -> {new_channels_hash}, "
            f"heartbeat: {old_heartbeat_hash} -> {new_heartbeat_hash})",
        )
        try:
            await manager.reload_agent(self._agent_id)
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"reload_agent failed",
            )
