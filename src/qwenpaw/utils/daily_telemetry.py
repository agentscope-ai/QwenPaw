# -*- coding: utf-8 -*-
"""Opt-in, daily Runtime activity telemetry with a durable outbox."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sqlite3
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..constant import EnvVarLoader, WORKING_DIR
from .telemetry import (
    _upload_telemetry_sync,
    get_environment_info,
    is_telemetry_opted_out,
)

logger = logging.getLogger(__name__)
DAILY_TELEMETRY_FILE = ".daily_telemetry.sqlite3"
ENABLED_ENV = "QWENPAW_DAILY_TELEMETRY_ENABLED"
_service: DailyTelemetry | None = None


@contextmanager
def _connect(directory: Path) -> Iterator[sqlite3.Connection]:
    """Initialize identity and outbox atomically across worker processes."""
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / DAILY_TELEMETRY_FILE, timeout=1)
    try:
        with db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                "runtime_id TEXT NOT NULL, enabled INTEGER NOT NULL)",
            )
            db.execute(
                "INSERT OR IGNORE INTO runtime VALUES (1, ?, 0)",
                (str(uuid.uuid4()),),
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS activity ("
                "day TEXT PRIMARY KEY, payload TEXT, sent INTEGER NOT NULL "
                "DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, "
                "next_attempt REAL NOT NULL DEFAULT 0)",
            )
            yield db
    finally:
        db.close()


def set_daily_telemetry_enabled(directory: Path, enabled: bool) -> None:
    """Save the Runtime choice without changing its persistent identity."""
    with _connect(directory) as db:
        db.execute("UPDATE runtime SET enabled = ?", (int(enabled),))
        if not enabled:
            db.execute("DELETE FROM activity WHERE sent = 0")


def daily_telemetry_enabled(directory: Path) -> bool:
    """Require explicit daily consent and honor the global opt-out."""
    if is_telemetry_opted_out(directory):
        return False
    if ENABLED_ENV in os.environ:
        return EnvVarLoader.get_bool(ENABLED_ENV)
    if not (directory / DAILY_TELEMETRY_FILE).exists():
        return False
    try:
        with _connect(directory) as db:
            return bool(
                db.execute("SELECT enabled FROM runtime").fetchone()[0],
            )
    except (OSError, sqlite3.Error):
        logger.debug("Cannot read daily telemetry choice", exc_info=True)
        return False


class DailyTelemetry:
    """One sender per process; the receiver deduplicates across processes."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._wake = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Retry existing activity without creating startup activity."""
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        """Allow bounded, already-started network work to finish."""
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=15)
            except asyncio.TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)

    async def record(self, day: str | None = None) -> bool:
        """Persist the observation date before any slow environment probe."""
        if self._stopping:
            return False
        day = day or datetime.now(timezone.utc).date().isoformat()
        try:
            recorded = await asyncio.to_thread(self._record_sync, day)
            self._wake.set()
            return recorded
        except (OSError, sqlite3.Error):
            logger.debug("Cannot record daily activity", exc_info=True)
            return False

    def _record_sync(self, day: str) -> bool:
        if not daily_telemetry_enabled(self.directory):
            return False
        with _connect(self.directory) as db:
            db.execute(
                "INSERT OR IGNORE INTO activity(day) VALUES (?)",
                (day,),
            )
        return True

    async def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                await asyncio.to_thread(self.flush)
            except Exception:
                logger.debug("Daily telemetry failed", exc_info=True)
            if self._stopping:
                break
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    def flush(self) -> None:
        """Send due observations, preserving their original date/snapshot."""
        if not daily_telemetry_enabled(self.directory):
            if (self.directory / DAILY_TELEMETRY_FILE).exists():
                with _connect(self.directory) as db:
                    db.execute("DELETE FROM activity WHERE sent = 0")
            return
        today = datetime.now(timezone.utc).date()
        cutoff = (today - timedelta(days=6)).isoformat()
        with _connect(self.directory) as db:
            db.execute("DELETE FROM activity WHERE day < ?", (cutoff,))
            rows = db.execute(
                "SELECT day, payload, attempts FROM activity "
                "WHERE sent = 0 AND day <= ? AND next_attempt <= ? "
                "ORDER BY day",
                (today.isoformat(), time.time()),
            ).fetchall()
            runtime_id = db.execute(
                "SELECT runtime_id FROM runtime",
            ).fetchone()[0]
        environment = None
        for day, payload, attempts in rows:
            if self._stopping:
                return
            if payload is None:
                if environment is None:
                    environment = get_environment_info()
                event = {
                    **environment,
                    "schema_version": 2,
                    "event_type": "runtime_active",
                    "telemetry_runtime_id": runtime_id,
                    "activity_date": day,
                    "deployment_mode": (
                        "hub"
                        if EnvVarLoader.get_str("QWENPAW_RUNTIME_ID")
                        else "standalone"
                    ),
                }
                with _connect(self.directory) as db:
                    db.execute(
                        "UPDATE activity SET payload = ? "
                        "WHERE day = ? AND payload IS NULL",
                        (json.dumps(event), day),
                    )
                    saved = db.execute(
                        "SELECT payload FROM activity WHERE day = ?",
                        (day,),
                    ).fetchone()
                if saved is None:
                    continue
                payload = saved[0]
            if self._stopping or not daily_telemetry_enabled(self.directory):
                return
            success = _upload_telemetry_sync(json.loads(payload))
            delay = min(60 * 2 ** min(attempts, 10), 3600)
            with _connect(self.directory) as db:
                db.execute(
                    "UPDATE activity SET sent = ?, attempts = attempts + 1, "
                    "next_attempt = ? WHERE day = ? AND sent = 0",
                    (
                        int(success),
                        time.time() + delay + random.uniform(0, delay / 4),
                        day,
                    ),
                )


def start_daily_telemetry() -> DailyTelemetry:
    """Attach the single Runtime sender to the application lifespan."""
    global _service  # pylint: disable=global-statement
    _service = DailyTelemetry(WORKING_DIR)
    _service.start()
    return _service


async def record_activity(source: str) -> bool:
    """Accept only explicit human entry points; never count startup/timers."""
    if source in {"page", "message", "operation"} and _service is not None:
        return await _service.record()
    return False


async def record_channel_activity(request: Any) -> None:
    """Called only after a channel has accepted an inbound request."""
    context = getattr(request, "request_context", None) or {}
    if context.get("source") or context.get("_spawn_subagent"):
        return
    await record_activity("message")
