# -*- coding: utf-8 -*-
"""Watch config.json for changes and auto-reload channels."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .utils import load_config, get_config_path
from .config import ChannelConfig
from ..app.channels import ChannelManager  # pylint: disable=no-name-in-module
from .utils import get_available_channels

logger = logging.getLogger(__name__)

# How often to poll (seconds)
DEFAULT_POLL_INTERVAL = 2.0


class ConfigWatcher:
    """Poll config.json mtime; reload only changed channels automatically."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        config_path: Optional[Path] = None,
    ):
        self._channel_manager = channel_manager
        self._poll_interval = poll_interval
        self._config_path = config_path or get_config_path()
        self._task: Optional[asyncio.Task] = None

        # Snapshot of the last known channel config (for diffing)
        self._last_channels: Optional[ChannelConfig] = None
        self._last_channels_hash: Optional[int] = None
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
        """Load current config and record mtime + channels hash."""
        try:
            self._last_mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            self._last_mtime = 0.0
        try:
            config = load_config(self._config_path)
            self._last_channels = config.channels.model_copy(deep=True)
            self._last_channels_hash = self._channels_hash(config.channels)
        except Exception:
            logger.exception("ConfigWatcher: failed to load initial config")
            self._last_channels = None
            self._last_channels_hash = None

    @staticmethod
    def _channels_hash(channels: ChannelConfig) -> int:
        """Fast hash of channels section for quick change detection."""
        return hash(str(channels.model_dump(mode="json")))

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check()
            except Exception:
                logger.exception("ConfigWatcher: poll iteration failed")

    async def _check(self) -> None:
        # 1) Check mtime
        try:
            mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime

        # 2) Load new config; quick-reject if channels section unchanged
        try:
            config = load_config(self._config_path)
        except Exception:
            logger.exception("ConfigWatcher: failed to parse config.json")
            return

        new_hash = self._channels_hash(config.channels)
        if new_hash == self._last_channels_hash:
            return  # Only non-channel fields changed (e.g. last_dispatch)

        # 3) Diff per-channel and reload changed ones
        new_channels = config.channels
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

            if isinstance(new_ch, dict):
                new_dump = new_ch
                old_dump = old_ch if isinstance(old_ch, dict) else None
            else:
                new_dump = (
                    new_ch.model_dump(mode="json")
                    if hasattr(new_ch, "model_dump")
                    else None
                )
                old_dump = (
                    old_ch.model_dump(mode="json")
                    if old_ch and hasattr(old_ch, "model_dump")
                    else None
                )
            if new_dump is not None and new_dump == old_dump:
                continue

            logger.info(
                f"ConfigWatcher: channel '{name}' config changed, reloading",
            )
            try:
                old_channel = await self._channel_manager.get_channel(name)
                if old_channel is None:
                    logger.warning(
                        f"ConfigWatcher: channel '{name}' not found, skip",
                    )
                    continue
                new_channel = old_channel.clone(new_ch)
                await self._channel_manager.replace_channel(new_channel)
                logger.info(f"ConfigWatcher: channel '{name}' reloaded")
            except Exception:
                # Reload failed — keep old snapshot for this channel so
                # the next config change will retry the reload.
                logger.exception(
                    f"ConfigWatcher: failed to reload channel '{name}'",
                )
                setattr(new_channels, name, old_ch if old_ch else new_ch)

        # 4) Update snapshot
        self._last_channels = new_channels.model_copy(deep=True)
        self._last_channels_hash = self._channels_hash(new_channels)
