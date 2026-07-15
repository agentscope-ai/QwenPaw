# -*- coding: utf-8 -*-
"""Abstract base class for notification backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class NotificationBackend(ABC):
    """Interface that all platform backends must implement."""

    @abstractmethod
    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
        group: str = "QwenPaw",
    ) -> bool:
        """Send a desktop notification. Return True on success."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend can function on the current platform."""
