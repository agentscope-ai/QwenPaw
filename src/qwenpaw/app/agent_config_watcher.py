# -*- coding: utf-8 -*-
"""Watch agent.json for changes and auto-reload agent components.

This watcher monitors an agent's workspace/agent.json file for changes
and automatically reloads channels, heartbeat, and other configurations
without requiring manual restart.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from ..config.config import load_agent_config
from ..config.utils import get_available_channels

if TYPE_CHECKING:
    from ..config.config import ChannelConfig, HeartbeatConfig

logger = logging.getLogger(__name__)

# How often to poll (seconds)
DEFAULT_POLL_INTERVAL = 2.0


def _heartbeat_hash(hb: Optional[HeartbeatConfig]) -> int:
    """Hash of heartbeat config for change detection."""
    if hb is None:
        return hash("None")
    return hash(str(hb.model_dump(mode="json")))


def _memory_job_hash(memory_summary: Any) -> int:
    """Hash of memory job config for change detection."""
    if memory_summary is None:
        return hash("None")
    cron_expr = getattr(memory_summary, "memory_consolidation_cron", "")
    return hash(str(cron_expr))


class AgentConfigWatcher:
    """Poll agent.json mtime and reload changed configs automatically.

    This watcher is agent-scoped and monitors a specific agent's
    workspace/agent.json file for configuration changes.
    """

    def __init__(
        self,
        agent_id: str,
        workspace_dir: Path,
        channel_manager: Any,
        cron_manager: Any = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        """Initialize agent config watcher.

        Args:
            agent_id: Agent ID to monitor
            workspace_dir: Path to agent's workspace directory
            channel_manager: ChannelManager instance for this agent
            cron_manager: CronManager instance for this agent (optional)
            poll_interval: How often to check for changes (seconds)
        """
        self._agent_id = agent_id
        self._workspace_dir = workspace_dir
        self._config_path = workspace_dir / "agent.json"
        self._channel_manager = channel_manager
        self._cron_manager = cron_manager
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None

        # Snapshot of the last known config (for diffing)
        self._last_channels: Optional[ChannelConfig] = None
        self._last_channels_hash: Optional[int] = None
        self._last_heartbeat_hash: Optional[int] = None
        self._last_memory_job_hash: Optional[int] = None
        # mtime of agent.json at last check
        self._last_mtime: float = 0.0

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
        """Stop the polling task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"AgentConfigWatcher stopped for agent {self._agent_id}")

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _snapshot(self) -> None:
        """Load current agent config; record mtime and hashes."""
        try:
            self._last_mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            self._last_mtime = 0.0

        try:
            agent_config = load_agent_config(self._agent_id)
            if agent_config.channels:
                self._last_channels = agent_config.channels.model_copy(
                    deep=True,
                )
                self._last_channels_hash = self._channels_hash(
                    agent_config.channels,
                )
            else:
                self._last_channels = None
                self._last_channels_hash = None

            self._last_heartbeat_hash = _heartbeat_hash(
                agent_config.heartbeat,
            )
            self._last_memory_job_hash = _memory_job_hash(
                getattr(agent_config, "memory_summary", None),
            )
        except Exception:
            logger.exception(
                f"AgentConfigWatcher: failed to load initial config "
                f"for agent {self._agent_id}",
            )
            self._last_channels = None
            self._last_channels_hash = None
            self._last_heartbeat_hash = None
            self._last_memory_job_hash = None

    @staticmethod
    def _channels_hash(channels: ChannelConfig) -> int:
        """Fast hash of channels section for quick change detection."""
        return hash(str(channels.model_dump(mode="json")))

    @staticmethod
    def _channel_dump(ch: Any) -> Any:
        """Return JSON-serializable dict for channel config, or None."""
        if ch is None:
            return None
        if isinstance(ch, dict):
            return ch
        if hasattr(ch, "model_dump"):
            return ch.model_dump(mode="json")
        return None

    async def _reload_one_channel(
        self,
        name: str,
        new_ch: Any,
        new_channels: ChannelConfig,
        old_ch: Any,
    ) -> None:
        """Reload a single channel; on failure revert new_channels entry."""
        try:
            old_channel = await self._channel_manager.get_channel(name)
            if old_channel is None:
                logger.warning(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"channel '{name}' not found, skip",
                )
                return
            new_channel = old_channel.clone(new_ch)
            await self._channel_manager.replace_channel(new_channel)
            logger.info(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"channel '{name}' reloaded",
            )
        except Exception:
            logger.exception(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"failed to reload channel '{name}'",
            )
            setattr(new_channels, name, old_ch if old_ch else new_ch)

    async def _apply_channel_changes(self, agent_config: Any) -> None:
        """Diff channels and reload changed ones; update snapshot."""
        if not agent_config.channels:
            return

        new_hash = self._channels_hash(agent_config.channels)
        if new_hash == self._last_channels_hash:
            return

        new_channels = agent_config.channels
        old_channels = self._last_channels
        extra_new = getattr(new_channels, "__pydantic_extra__", None) or {}
        extra_old = (
            getattr(old_channels, "__pydantic_extra__", None)
            if old_channels
            else {}
        )

        for name in get_available_channels():
            new_ch = getattr(new_channels, name, None) or extra_new.get(name)
            old_ch = (
                getattr(old_channels, name, None) or extra_old.get(name)
                if old_channels
                else None
            )
            if new_ch is None:
                continue
            new_dump = self._channel_dump(new_ch)
            old_dump = self._channel_dump(old_ch)
            if new_dump is not None and new_dump == old_dump:
                continue
            logger.info(
                f"AgentConfigWatcher ({self._agent_id}): "
                f"channel '{name}' config changed, reloading",
            )
            await self._reload_one_channel(name, new_ch, new_channels, old_ch)

        self._last_channels = new_channels.model_copy(deep=True)
        self._last_channels_hash = self._channels_hash(new_channels)

    async def _apply_heartbeat_change(self, agent_config: Any) -> None:
        """Update heartbeat hash and reschedule if changed."""
        new_hb_hash = _heartbeat_hash(agent_config.heartbeat)
        if (
            self._cron_manager is not None
            and new_hb_hash != self._last_heartbeat_hash
        ):
            self._last_heartbeat_hash = new_hb_hash
            try:
                await self._cron_manager.reschedule_heartbeat()
                logger.info(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"heartbeat rescheduled",
                )
            except Exception:
                logger.exception(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"failed to reschedule heartbeat",
                )
        else:
            self._last_heartbeat_hash = new_hb_hash

    async def _apply_memory_job_change(self, agent_config: Any) -> None:
        """Update memory job hash and reschedule if changed."""
        new_memory_summary = getattr(agent_config, "memory_summary", None)
        new_memory_job_hash = _memory_job_hash(new_memory_summary)
        if (
            self._cron_manager is not None
            and new_memory_job_hash != self._last_memory_job_hash
        ):
            self._last_memory_job_hash = new_memory_job_hash
            try:
                await self._cron_manager.reschedule_memory()
                logger.info(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"memory job rescheduled",
                )
            except Exception:
                logger.exception(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"failed to reschedule memory job",
                )
        else:
            self._last_memory_job_hash = new_memory_job_hash

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check()
            except Exception:
                logger.exception(
                    f"AgentConfigWatcher ({self._agent_id}): "
                    f"poll iteration failed",
                )

    async def _check(self) -> None:
        """Check for config changes and reload if needed."""
        try:
            mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            return

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

        # Apply changes
        if self._channel_manager:
            await self._apply_channel_changes(agent_config)
        if self._cron_manager:
            await self._apply_heartbeat_change(agent_config)
            await self._apply_memory_job_change(agent_config)
