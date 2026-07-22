# -*- coding: utf-8 -*-
"""Singleton manager for message recording lifecycle."""

import logging
import threading
from typing import Optional

from ..constant import WORKING_DIR
from .buffer import MessageRecordingBuffer, _MessageEvent

logger = logging.getLogger(__name__)

_DEFAULT_STORAGE_DIR = WORKING_DIR / "message_logs"
_DEFAULT_FLUSH_INTERVAL = 5
_DEFAULT_RETENTION_DAYS = 3


class MessageRecordingManager:
    """Orchestrator for message recording.

    The manager does NOT gate recording via an ``enabled`` flag.
    Middleware presence (registered only when enabled in config)
    determines whether an agent records.

    ``retention_days`` is a global setting loaded once at startup.
    Per-agent ``configure()`` calls do NOT update retention to
    avoid multi-agent pollution (last-agent-wins problem).
    """

    _instance: "MessageRecordingManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._buffer: Optional[MessageRecordingBuffer] = None
        self._started: bool = False

    @classmethod
    def get_instance(cls) -> "MessageRecordingManager":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start(
        self,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
    ) -> None:
        """Create buffer and start background tasks.

        Args:
            retention_days: File cleanup threshold. Must be
                loaded from config BEFORE calling start() to
                avoid deleting files with the wrong default.
        """
        if self._started:
            return
        self._started = True

        self._buffer = MessageRecordingBuffer(
            base_dir=_DEFAULT_STORAGE_DIR,
            flush_interval=_DEFAULT_FLUSH_INTERVAL,
            retention_days=retention_days,
        )
        self._buffer.start()

    def update_retention_days(self, days: int) -> None:
        """Update retention policy on the running buffer.

        Called from the workspace API endpoint when the user
        changes retention_days in the UI. NOT called from
        builder.py to avoid multi-agent pollution.
        """
        if self._buffer is not None:
            self._buffer.update_retention_days(days)

    async def stop(self) -> None:
        """Stop buffer and flush remaining records."""
        if self._buffer is not None:
            await self._buffer.stop()
        self._started = False

    def enqueue(self, event: _MessageEvent) -> None:
        """Enqueue a recording event.

        Middleware presence gates whether this is called.
        The manager unconditionally forwards to buffer.
        """
        if self._buffer is None:
            return
        self._buffer.enqueue(event)


def get_message_recording_manager() -> MessageRecordingManager:
    """Get or create the singleton MessageRecordingManager."""
    return MessageRecordingManager.get_instance()
