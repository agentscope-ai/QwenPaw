# -*- coding: utf-8 -*-
"""Async write buffer with producer-consumer for message recording."""

import asyncio
import datetime
import json
import logging
import time
from pathlib import Path
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

_DEFAULT_FLUSH_INTERVAL = 5  # seconds
_CLEANUP_INTERVAL = 86400  # 1 day in seconds


class _MessageEvent(NamedTuple):
    """Immutable record placed on the queue by the producer."""

    timestamp: str
    request_id: str
    session_id: str
    agent_id: str
    provider_id: str
    model_name: str
    messages: str  # pre-serialized JSON string
    tools: str  # pre-serialized JSON string
    tool_choice: str  # pre-serialized JSON string
    response: str  # pre-serialized JSON string
    duration_ms: int


class MessageRecordingBuffer:
    """Async producer-consumer buffer that flushes to JSONL files."""

    def __init__(
        self,
        base_dir: Path,
        flush_interval: int = _DEFAULT_FLUSH_INTERVAL,
        retention_days: int = 3,
    ) -> None:
        self._base_dir = base_dir
        self._flush_interval = flush_interval
        self._retention_days = retention_days

        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._pending: list[_MessageEvent] = []
        self._consumer_task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._stopped = False
        self._last_cleanup_time: float = 0.0

    def start(self) -> None:
        """Start consumer and flush tasks."""
        if self._consumer_task is not None:
            return
        self._stopped = False
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._consumer_task = asyncio.create_task(
            self._consumer_loop(),
            name="msg-recording-consumer",
        )
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="msg-recording-flush",
        )

    def update_retention_days(self, days: int) -> None:
        """Update retention_days for cleanup policy."""
        self._retention_days = days

    async def stop(self) -> None:
        """Drain queue, stop tasks, perform final flush."""
        self._stopped = True

        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        if self._consumer_task is not None:
            await self._queue.join()
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        await self._flush_once()

    def enqueue(self, event: _MessageEvent) -> None:
        """Put an event on the queue (sync, non-blocking)."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "message_recording: queue full, " + "dropping event for %s:%s",
                event.provider_id,
                event.model_name,
            )

    async def _consumer_loop(self) -> None:
        """Drain events from queue into pending list."""
        try:
            while True:
                event = await self._queue.get()
                try:
                    self._pending.append(event)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            while not self._queue.empty():
                try:
                    event = self._queue.get_nowait()
                    self._pending.append(event)
                    self._queue.task_done()
                except asyncio.QueueEmpty:
                    break

    async def _flush_once(self) -> None:
        """Swap pending list and write to JSONL files."""
        if not self._pending:
            return

        records = self._pending
        self._pending = []

        # Group by date
        by_date: dict[str, list[str]] = {}
        for event in records:
            # Extract date from ISO timestamp
            date_str = event.timestamp[:10]
            line = _build_jsonl_line(event)
            by_date.setdefault(date_str, []).append(line)

        for date_str, lines in by_date.items():
            file_path = self._base_dir / f"{date_str}.jsonl"
            try:
                await asyncio.to_thread(
                    _append_records_sync,
                    file_path,
                    lines,
                )
            except Exception:
                logger.warning(
                    "message_recording: failed to write %s",
                    file_path,
                    exc_info=True,
                )

    async def _flush_loop(self) -> None:
        """Periodically flush pending records and cleanup old files."""
        # Run cleanup once at start
        await self._run_cleanup()
        try:
            while not self._stopped:
                await asyncio.sleep(self._flush_interval)
                try:
                    await self._flush_once()
                except Exception:
                    logger.warning(
                        "message_recording: flush error",
                        exc_info=True,
                    )
                # Cleanup old files once per day
                now = time.monotonic()
                if now - self._last_cleanup_time >= _CLEANUP_INTERVAL:
                    await self._run_cleanup()
        except asyncio.CancelledError:
            pass

    async def _run_cleanup(self) -> None:
        """Delete JSONL files older than retention_days."""
        self._last_cleanup_time = time.monotonic()
        try:
            await asyncio.to_thread(
                _cleanup_old_files,
                self._base_dir,
                self._retention_days,
            )
        except Exception:
            logger.debug(
                "message_recording: cleanup error",
                exc_info=True,
            )


def _append_records_sync(
    file_path: Path,
    lines: list[str],
) -> None:
    """Append JSONL lines to file (sync, called via to_thread)."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "a", encoding="utf-8") as f:
        f.writelines(lines)


def _cleanup_old_files(
    base_dir: Path,
    retention_days: int,
) -> None:
    """Remove JSONL files older than retention_days."""
    if not base_dir.exists():
        return

    cutoff = datetime.date.today() - datetime.timedelta(days=retention_days)

    for path in base_dir.glob("*.jsonl"):
        try:
            file_date = datetime.date.fromisoformat(path.stem)
            if file_date < cutoff:
                path.unlink()
                logger.debug(
                    "message_recording: removed old file %s",
                    path.name,
                )
        except (ValueError, OSError):
            pass


def _build_jsonl_line(event: _MessageEvent) -> str:
    """Build a single JSONL line from an event.

    Scalar fields are JSON-escaped via json.dumps to prevent
    injection. Pre-serialized JSON fields (messages, tools,
    tool_choice, response) are embedded directly.
    """
    # JSON-escape scalar string fields
    ts = json.dumps(event.timestamp)
    req_id = json.dumps(event.request_id)
    sess_id = json.dumps(event.session_id)
    agent = json.dumps(event.agent_id)
    provider = json.dumps(event.provider_id)
    model = json.dumps(event.model_name)

    return (
        f'{{"timestamp": {ts}'
        f', "request_id": {req_id}'
        f', "session_id": {sess_id}'
        f', "agent_id": {agent}'
        f', "provider_id": {provider}'
        f', "model": {model}'
        f', "messages": {event.messages}'
        f', "tools": {event.tools}'
        f', "tool_choice": {event.tool_choice}'
        f', "response": {event.response}'
        f', "duration_ms": {event.duration_ms}'
        f"}}\n"
    )


__all__ = ["MessageRecordingBuffer", "_MessageEvent"]
