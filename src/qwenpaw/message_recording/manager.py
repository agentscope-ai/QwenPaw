# -*- coding: utf-8 -*-
"""Singleton manager for message recording lifecycle."""

import logging
import threading
from typing import TYPE_CHECKING, Optional

from ..constant import WORKING_DIR
from .buffer import MessageRecordingBuffer, _MessageEvent

if TYPE_CHECKING:
    from ..config.config import MessageRecordingConfig

logger = logging.getLogger(__name__)

_DEFAULT_STORAGE_DIR = WORKING_DIR / "message_logs"
_DEFAULT_FLUSH_INTERVAL = 5
_DEFAULT_RETENTION_DAYS = 3


class MessageRecordingManager:
    """Orchestrator for message recording."""

    _instance: "MessageRecordingManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._buffer: Optional[MessageRecordingBuffer] = None
        self._enabled: bool = False
        self._started: bool = False

    @classmethod
    def get_instance(cls) -> "MessageRecordingManager":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def enabled(self) -> bool:
        """Whether recording is currently enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def configure(
        self,
        config: "MessageRecordingConfig",
    ) -> None:
        """Update enabled state and retention policy from config.

        Does NOT recreate buffer. Buffer lifecycle is managed
        by start()/stop() called from _app.py.
        """
        self._enabled = config.enabled
        if self._buffer is not None:
            self._buffer.update_retention_days(
                config.retention_days,
            )

    def start(self) -> None:
        """Create buffer and start background tasks.

        Uses default storage_dir and flush_interval.
        Must be called from an async context.
        """
        if self._started:
            return
        self._started = True

        storage_dir = _DEFAULT_STORAGE_DIR
        self._buffer = MessageRecordingBuffer(
            base_dir=storage_dir,
            flush_interval=_DEFAULT_FLUSH_INTERVAL,
            retention_days=_DEFAULT_RETENTION_DAYS,
        )
        self._buffer.start()

    async def stop(self) -> None:
        """Stop buffer and flush remaining records."""
        if self._buffer is not None:
            await self._buffer.stop()
        self._started = False

    def enqueue(self, event: _MessageEvent) -> None:
        """Enqueue a recording event (no-op if disabled)."""
        if not self._enabled:
            return
        if self._buffer is None:
            return
        self._buffer.enqueue(event)


def get_message_recording_manager() -> MessageRecordingManager:
    """Get or create the singleton MessageRecordingManager."""
    return MessageRecordingManager.get_instance()
