# -*- coding: utf-8 -*-
"""Singleton manager for message recording lifecycle."""

import logging
import os
import threading
from typing import Optional

from ..constant import WORKING_DIR
from .buffer import MessageRecordingBuffer, _MessageEvent

logger = logging.getLogger(__name__)

_DEFAULT_STORAGE_DIR = WORKING_DIR / "message_logs"
_DEFAULT_FLUSH_INTERVAL = 5
_DEFAULT_RETENTION_DAYS = 3
_ENV_RETENTION_DAYS = "QWENPAW_MESSAGE_RECORDING_RETENTION_DAYS"


def _get_retention_days() -> int:
    """Read retention_days from env var or use default."""
    raw = os.environ.get(_ENV_RETENTION_DAYS)
    if raw is None:
        return _DEFAULT_RETENTION_DAYS
    try:
        val = int(raw)
        return max(1, min(val, 90))
    except ValueError:
        logger.warning(
            "Invalid %s=%r, using default %d",
            _ENV_RETENTION_DAYS,
            raw,
            _DEFAULT_RETENTION_DAYS,
        )
        return _DEFAULT_RETENTION_DAYS


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

        Retention is read from the env var
        QWENPAW_MESSAGE_RECORDING_RETENTION_DAYS (default 3,
        clamped to 1..90). Must be called from an async context.
        """
        if self._started:
            return
        self._started = True

        retention = _get_retention_days()
        self._buffer = MessageRecordingBuffer(
            base_dir=_DEFAULT_STORAGE_DIR,
            flush_interval=_DEFAULT_FLUSH_INTERVAL,
            retention_days=retention,
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
