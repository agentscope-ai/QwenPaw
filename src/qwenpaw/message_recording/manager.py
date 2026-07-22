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

    Middleware presence (registered only when enabled in config)
    determines whether an agent records. Retention is a
    process-global constant, not configurable per agent.
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

    def start(self) -> None:
        """Create buffer and start background tasks.

        Must be called from an async context.
        """
        if self._started:
            return
        self._started = True

        self._buffer = MessageRecordingBuffer(
            base_dir=_DEFAULT_STORAGE_DIR,
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
