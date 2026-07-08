# -*- coding: utf-8 -*-
"""NotificationService — orchestrates backend selection and rate-limiting."""

from __future__ import annotations

import logging
import time
from typing import Any

from qwenpaw.config.config import NotificationConfig

from .backends.base import NotificationBackend
from .backends.desktop import DesktopNotifierBackend
from .backends.linux_fallback import LinuxFallbackBackend
from .backends.macos_fallback import MacOSFallbackBackend
from .matcher import event_matches_rules

logger = logging.getLogger(__name__)


class NotificationService:
    """Singleton-style service that manages notification dispatch.

    Handles:
    - Backend auto-selection with fallback chain
    - Rate-limiting to prevent notification storms
    - Batching excess events into a summary notification
    """

    def __init__(self) -> None:
        self._backends: list[NotificationBackend] = []
        self._last_sent_at: float = 0.0
        self._pending_count: int = 0
        self._init_backends()

    def _init_backends(self) -> None:
        """Build the ordered backend list for the current platform."""
        desktop = DesktopNotifierBackend()
        if desktop.is_available():
            self._backends.append(desktop)

        macos_fb = MacOSFallbackBackend()
        if macos_fb.is_available():
            self._backends.append(macos_fb)

        linux_fb = LinuxFallbackBackend()
        if linux_fb.is_available():
            self._backends.append(linux_fb)

    @property
    def available(self) -> bool:
        """Whether at least one backend can deliver notifications."""
        return len(self._backends) > 0

    async def notify_event(
        self,
        event: dict[str, Any],
        config: NotificationConfig,
    ) -> None:
        """Check rules, rate-limit, and dispatch notification for *event*."""
        if not config.enabled:
            return
        if not self._backends:
            return
        if not event_matches_rules(event, config):
            return

        now = time.time()
        min_interval = config.min_interval_seconds

        if now - self._last_sent_at < min_interval:
            self._pending_count += 1
            return

        if self._pending_count > 0:
            title = "QwenPaw"
            body = f"{self._pending_count + 1} new inbox messages"
            self._pending_count = 0
        else:
            title = self._format_title(event)
            body = self._format_body(event)

        self._last_sent_at = now
        await self._send(title, body, sound=config.sound)

    async def send_test(self, config: NotificationConfig) -> bool:
        """Send a test notification, bypassing rules and rate-limit."""
        if not self._backends:
            return False
        return await self._send(
            title="QwenPaw Test",
            body="System notifications are working!",
            sound=config.sound,
        )

    async def _send(self, title: str, body: str, *, sound: bool) -> bool:
        """Try backends in order until one succeeds."""
        for backend in self._backends:
            try:
                ok = await backend.send(title, body, sound=sound)
                if ok:
                    return True
            except Exception as exc:
                logger.debug(
                    "Backend %s failed: %s",
                    type(backend).__name__,
                    exc,
                )
        return False

    @staticmethod
    def _format_title(event: dict[str, Any]) -> str:
        source = event.get("source_type", "")
        severity = event.get("severity", "info")
        prefix = ""
        if severity == "error":
            prefix = "[Error] "
        elif severity == "warning":
            prefix = "[Warning] "
        return f"{prefix}QwenPaw - {source}"

    @staticmethod
    def _format_body(event: dict[str, Any]) -> str:
        title = event.get("title", "")
        body = event.get("body", "")
        if title and body:
            combined = f"{title}\n{body}"
        else:
            combined = title or body or "New notification"
        # Truncate to reasonable length for desktop notification
        if len(combined) > 200:
            combined = combined[:197] + "..."
        return combined


_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get or create the global NotificationService instance."""
    global _service
    if _service is None:
        _service = NotificationService()
    return _service
