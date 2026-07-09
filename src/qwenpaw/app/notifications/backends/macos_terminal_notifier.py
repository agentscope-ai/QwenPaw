# -*- coding: utf-8 -*-
"""macOS backend using terminal-notifier (supports click-to-open URL)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from .base import NotificationBackend

logger = logging.getLogger(__name__)


class TerminalNotifierBackend(NotificationBackend):
    """macOS backend using terminal-notifier CLI.

    Supports click-to-open-URL via the -open flag.
    Install with: brew install terminal-notifier
    """

    def __init__(self) -> None:
        self._bin: str | None = None
        if sys.platform == "darwin":
            self._bin = shutil.which("terminal-notifier")

    def is_available(self) -> bool:
        return self._bin is not None

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
        url: str | None = None,
    ) -> bool:
        if self._bin is None:
            return False
        cmd = [
            self._bin,
            "-title",
            title,
            "-message",
            body,
            "-group",
            "QwenPaw",
            "-sender",
            "com.apple.Terminal",
        ]
        if sound:
            cmd.extend(["-sound", "default"])
        if url:
            cmd.extend(["-open", url])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                logger.debug(
                    "terminal-notifier failed: %s",
                    stderr.decode(errors="replace"),
                )
                return False
            return True
        except Exception as exc:
            logger.debug("terminal-notifier error: %s", exc)
            return False
