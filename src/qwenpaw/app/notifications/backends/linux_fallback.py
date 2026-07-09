# -*- coding: utf-8 -*-
"""Linux fallback using notify-send CLI."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from .base import NotificationBackend

logger = logging.getLogger(__name__)


class LinuxFallbackBackend(NotificationBackend):
    """Fallback for Linux when desktop-notifier is unavailable or fails.

    Uses `notify-send` which is available on most Linux desktops
    (libnotify-bin / libnotify package).
    """

    def is_available(self) -> bool:
        if sys.platform != "linux":
            return False
        return shutil.which("notify-send") is not None

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
        url: str | None = None,
    ) -> bool:
        try:
            cmd = ["notify-send", "--app-name=QwenPaw", title, body]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                logger.debug(
                    "notify-send failed: %s",
                    stderr.decode(errors="replace"),
                )
                return False
            return True
        except Exception as exc:
            logger.debug("Linux fallback notification error: %s", exc)
            return False
