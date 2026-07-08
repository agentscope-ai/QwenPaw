# -*- coding: utf-8 -*-
"""macOS fallback using osascript (AppleScript display notification)."""

from __future__ import annotations

import asyncio
import logging
import sys

from .base import NotificationBackend

logger = logging.getLogger(__name__)


class MacOSFallbackBackend(NotificationBackend):
    """Fallback for macOS when desktop-notifier is unavailable or fails.

    Uses `osascript -e 'display notification ...'` which works without
    code-signing requirements.
    """

    def is_available(self) -> bool:
        return sys.platform == "darwin"

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
    ) -> bool:
        escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
        escaped_body = body.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'display notification "{escaped_body}" '
            f'with title "{escaped_title}"'
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
