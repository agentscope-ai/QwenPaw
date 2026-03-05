# -*- coding: utf-8 -*-
"""Watch config.json for changes and auto-reload channels and heartbeat."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from .utils import load_config, get_config_path, get_available_channels
from .config import ChannelConfig, HeartbeatConfig
from ..app.channels import ChannelManager  # pylint: disable=no-name-in-module

logger = logging.getLogger(__name__)

# How often to poll (seconds)
DEFAULT_POLL_INTERVAL = 2.0


def _heartbeat_hash(hb: Optional[HeartbeatConfig]) -> int:
    """Hash of heartbeat config for change detection."""
    if hb is None:
        return hash("None")
    return hash(str(hb.model_dump(mode="json")))


class ConfigWatcher:
    """Poll config.json mtime; reload only changed channels automatically."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        config_path: Optional[Path] = None,
        cron_manager: Any = None,
    ):
        self._channel_manager = channel_manager
        self._poll_interval = poll_interval
        self._config_path = config_path or get_config_path()
        self._cron_manager = cron_manager
        self._task: Optional[asyncio.Task] = None

        # Snapshot of the last known channel config (for diffing)
        self._last_channels: Optional[ChannelConfig] = None
        self._last_channels_hash: Optional[int] = None
        self._last_heartbeat_hash: Optional[int] = None
        # mtime of config.json at last check
        self._last_mtime: float = 0.0

    async def start(self) -> None:
        """Take initial snapshot and start the polling task."""
        self._snapshot()
        self._task = asyncio.create_task(
            self._poll_loop(),
            name="config_watcher",
        )
        logger.info(
            "ConfigWatcher started (poll=%.1fs, path=%s)",
            self._poll_interval,
            self._config_path,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ConfigWatcher stopped")

    # ------------------------------------------------------------------

    def _snapshot(self) -> None:
        """Load current config; record mtime, channels hash, heartbeat hash."""
        try:
            self._last_mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            self._last_mtime = 0.0
        try:
            config = load_config(self._config_path)
            self._last_channels = config.channels.model_copy(deep=True)
            self._last_channels_hash = self._channels_hash(config.channels)
            hb = getattr(
                config.agents.defaults,
                "heartbeat",
                None,
            )
            self._last_heartbeat_hash = _heartbeat_hash(hb)
        except Exception:
            logger.exception("ConfigWatcher: failed to load initial config")
            self._last_channels = None
            self._last_channels_hash = None
            self._last_heartbeat_hash = None

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

    @staticmethod
    def _channel_keys(channels: Optional[ChannelConfig]) -> set[str]:
        """Return built-in + dynamic channel keys."""
        if channels is None:
            return set()
        keys = set(ChannelConfig.model_fields.keys())
        extra = getattr(channels, "__pydantic_extra__", None) or {}
        keys.update(extra.keys())
        return keys

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
                added = await self._channel_manager.add_channel(name, new_ch)
                if added:
                    logger.info("ConfigWatcher: channel '%s' added", name)
                else:
                    logger.warning(
                        "ConfigWatcher: channel '%s' not found, skip",
                        name,
                    )
                return
            new_channel = old_channel.clone(new_ch)
            await self._channel_manager.replace_channel(new_channel)
            logger.info("ConfigWatcher: channel '%s' reloaded", name)
        except Exception:
            logger.exception(
                "ConfigWatcher: failed to reload channel '%s'",
                name,
            )
            setattr(
                new_channels,
                name,
                old_ch if old_ch is not None else new_ch,
            )

    async def _apply_channel_changes(self, loaded_config: Any) -> None:
        """Diff channels and reload changed ones; update snapshot."""
        new_hash = self._channels_hash(loaded_config.channels)
        if new_hash == self._last_channels_hash:
            return
        new_channels = loaded_config.channels
        old_channels = self._last_channels
        extra_new_raw = getattr(new_channels, "__pydantic_extra__", None)
        extra_new: dict[str, Any] = (
            extra_new_raw if isinstance(extra_new_raw, dict) else {}
        )
        extra_old_raw = (
            getattr(old_channels, "__pydantic_extra__", None)
            if old_channels
            else None
        )
        extra_old: dict[str, Any] = (
            extra_old_raw if isinstance(extra_old_raw, dict) else {}
        )

        candidate_names = (
            set(get_available_channels())
            | self._channel_keys(new_channels)
            | self._channel_keys(old_channels)
        )
        removal_failed = False

        for name in sorted(candidate_names):
            new_ch = getattr(new_channels, name, None)
            if new_ch is None and name in extra_new:
                new_ch = extra_new.get(name)
            old_ch = (
                getattr(old_channels, name, None) if old_channels else None
            )
            if old_ch is None and name in extra_old:
                old_ch = extra_old.get(name)
            if new_ch is None:
                if old_ch is None:
                    continue
                logger.info(
                    "ConfigWatcher: channel '%s' removed from config, "
                    "stopping",
                    name,
                )
                try:
                    removed = await self._channel_manager.remove_channel(name)
                    if removed:
                        logger.info(
                            "ConfigWatcher: channel '%s' stopped and removed",
                            name,
                        )
                    else:
                        logger.warning(
                            "ConfigWatcher: channel '%s' missing in manager, "
                            "skip remove",
                            name,
                        )
                except Exception:
                    removal_failed = True
                    logger.exception(
                        "ConfigWatcher: failed to remove channel '%s'",
                        name,
                    )
                continue
            new_dump = self._channel_dump(new_ch)
            old_dump = self._channel_dump(old_ch)
            if new_dump is not None and new_dump == old_dump:
                continue
            logger.info(
                "ConfigWatcher: channel '%s' config changed, reloading",
                name,
            )
            await self._reload_one_channel(name, new_ch, new_channels, old_ch)
        if removal_failed:
            # Keep last snapshot and force next poll to retry removal.
            self._last_mtime = 0.0
            return
        self._last_channels = new_channels.model_copy(deep=True)
        self._last_channels_hash = self._channels_hash(new_channels)

    async def _apply_heartbeat_change(self, loaded_config: Any) -> None:
        """Update heartbeat hash and reschedule if changed."""
        hb = getattr(loaded_config.agents.defaults, "heartbeat", None)
        new_hb_hash = _heartbeat_hash(hb)
        if (
            self._cron_manager is not None
            and new_hb_hash != self._last_heartbeat_hash
        ):
            self._last_heartbeat_hash = new_hb_hash
            try:
                await self._cron_manager.reschedule_heartbeat()
                logger.info("ConfigWatcher: heartbeat rescheduled")
            except Exception:
                logger.exception(
                    "ConfigWatcher: failed to reschedule heartbeat",
                )
        else:
            self._last_heartbeat_hash = new_hb_hash

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check()
            except Exception:
                logger.exception("ConfigWatcher: poll iteration failed")

    async def _check(self) -> None:
        try:
            mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime
        try:
            loaded = load_config(self._config_path)
        except Exception:
            logger.exception("ConfigWatcher: failed to parse config.json")
            return
        await self._apply_channel_changes(loaded)
        await self._apply_heartbeat_change(loaded)
