# -*- coding: utf-8 -*-
"""macOS fallback using osascript ``display notification``.

This backend is used when both ``desktop-notifier`` and
``terminal-notifier`` are unavailable or have failed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .base import NotificationBackend

logger = logging.getLogger(__name__)

_WARNED_FALLBACK = False


class MacOSFallbackBackend(NotificationBackend):
    """Fallback for macOS using osascript ``display notification``."""

    def is_available(self) -> bool:
        return sys.platform == "darwin"

    @staticmethod
    def _escape(text: str) -> str:
        """Escape for AppleScript double-quoted strings."""
        return (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
    ) -> bool:
        global _WARNED_FALLBACK
        if not _WARNED_FALLBACK:
            _WARNED_FALLBACK = True
            logger.warning(
                "Using osascript fallback for notifications. "
                "For a better experience, install terminal-notifier: "
                "brew install terminal-notifier",
            )

        script = (
            f'display notification "{self._escape(body)}" '
            f'with title "{self._escape(title)}"'
        )
        if sound:
            script += ' sound name "default"'
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode != 0:
                logger.debug(
                    "osascript notification failed: %s",
                    stderr.decode(errors="replace"),
                )
                return False
            return True
        except Exception as exc:
            logger.debug("macOS fallback notification error: %s", exc)
            return False
