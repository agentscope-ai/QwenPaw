# -*- coding: utf-8 -*-
"""Async write buffer with producer-consumer for message recording."""

import asyncio
import datetime
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional

logger = logging.getLogger(__name__)

_DEFAULT_FLUSH_INTERVAL = 5  # seconds
_CLEANUP_INTERVAL = 86400  # 1 day in seconds

# Serialize file writes so a cancelled flush and a final
# flush never interleave on the same JSONL file.
_write_lock = threading.Lock()


class _MessageEvent(NamedTuple):
    """Immutable record placed on the queue by the producer.

    All fields store raw Python objects. Serialization happens
    in the worker thread during flush, keeping the event loop
    free from potentially expensive json.dumps calls.
    """

    timestamp: str
    request_id: str
    session_id: str
    agent_id: str
    provider_id: str
    model_name: str
    messages: Any  # list[dict] — raw structured data
    tools: Any  # list[dict] — raw structured data
    tool_choice: Any  # str | dict | None
    response: Any  # dict — raw structured data
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
        self._consumer_task = asyncio.create_task(
            self._consumer_loop(),
            name="msg-recording-consumer",
        )
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="msg-recording-flush",
        )

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

        # Serialization + file I/O all in worker thread
        await asyncio.to_thread(
            _serialize_and_write,
            records,
            self._base_dir,
        )

    async def _flush_loop(self) -> None:
        """Periodically flush pending records and cleanup.

        First cleanup runs after the first flush interval
        (not immediately on start), ensuring retention_days
        has been loaded from config.
        """
        _first_cleanup_done = False
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
                # First cleanup after first flush interval;
                # subsequent cleanups once per day.
                if not _first_cleanup_done:
                    _first_cleanup_done = True
                    await self._run_cleanup()
                else:
                    now = time.monotonic()
                    elapsed = now - self._last_cleanup_time
                    if elapsed >= _CLEANUP_INTERVAL:
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


def _serialize_and_write(
    records: list[_MessageEvent],
    base_dir: Path,
) -> None:
    """Serialize events and write to JSONL (runs in worker thread).

    Acquires _write_lock to prevent concurrent writes when a
    cancelled flush's thread overlaps with the final shutdown
    flush.
    """
    by_date: dict[str, list[str]] = {}
    for event in records:
        try:
            date_str = event.timestamp[:10]
            line = _build_jsonl_line(event)
        except Exception:
            logger.debug(
                "message_recording: failed to serialize event",
                exc_info=True,
            )
            continue
        by_date.setdefault(date_str, []).append(line)

    with _write_lock:
        for date_str, lines in by_date.items():
            file_path = base_dir / f"{date_str}.jsonl"
            try:
                file_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                with open(
                    file_path,
                    "a",
                    encoding="utf-8",
                ) as f:
                    f.writelines(lines)
            except Exception:
                logger.warning(
                    "message_recording: failed to write %s",
                    file_path,
                    exc_info=True,
                )


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
    """Build a JSONL line via single json.dumps call.

    All serialization happens here in the worker thread.
    """
    record = {
        "timestamp": event.timestamp,
        "request_id": event.request_id,
        "session_id": event.session_id,
        "agent_id": event.agent_id,
        "provider_id": event.provider_id,
        "model": event.model_name,
        "messages": event.messages,
        "tools": event.tools,
        "tool_choice": event.tool_choice,
        "response": event.response,
        "duration_ms": event.duration_ms,
    }
    return json.dumps(record, ensure_ascii=False) + "\n"


__all__ = ["MessageRecordingBuffer", "_MessageEvent"]
