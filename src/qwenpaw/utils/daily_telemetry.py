# -*- coding: utf-8 -*-
"""Daily Runtime activity telemetry with a durable outbox."""
from __future__ import annotations

import threading
import logging
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..constant import EnvVarLoader, WORKING_DIR
from .io_utils import run_sync_io
from .telemetry import (
    telemetry_marker,
    _upload_telemetry_sync,
    get_environment_info,
    is_telemetry_opted_out,
)

logger = logging.getLogger(__name__)
_service: DailyTelemetry | None = None


class DailyTelemetry:
    """One sender per process; the receiver deduplicates across processes."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._wake = threading.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Retry existing activity without creating startup activity."""
        self._thread = threading.Thread(
            target=self._run,
            name="qwenpaw-daily-telemetry",
            daemon=True,
        )
        self._thread.start()

    async def close(self) -> None:
        """Signal shutdown without waiting for detached network work."""
        self._stopping = True
        self._wake.set()

    async def record(self, day: str | None = None) -> bool:
        """Persist the observation date before any slow environment probe."""
        if self._stopping:
            return False
        day = day or datetime.now(timezone.utc).date().isoformat()
        try:
            recorded = await run_sync_io(self._record_sync, day)
            self._wake.set()
            return recorded
        except (OSError, ValueError):
            logger.debug("Cannot record daily activity", exc_info=True)
            return False

    def _record_sync(self, day: str) -> bool:
        if is_telemetry_opted_out(self.directory):
            return False
        with telemetry_marker(self.directory) as data:
            data.setdefault("telemetry_runtime_id", str(uuid.uuid4()))
            activity = data.setdefault("daily_activity", {})
            activity.setdefault(day, {})
        return True

    def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                self.flush()
            except Exception:
                logger.debug("Daily telemetry failed", exc_info=True)
            if self._stopping:
                break
            self._wake.wait(timeout=60)

    def flush(self) -> None:
        """Retry bounded daily records using the shared installation marker."""
        today = datetime.now(timezone.utc).date()
        cutoff = (today - timedelta(days=6)).isoformat()
        with telemetry_marker(self.directory) as data:
            activity = data.get("daily_activity", {})
            disabled = is_telemetry_opted_out(self.directory)
            for day in list(activity):
                if day < cutoff or (
                    disabled and not activity[day].get("sent")
                ):
                    del activity[day]
            if disabled:
                return
            runtime_id = data.get("telemetry_runtime_id")
            pending = {
                day: dict(event)
                for day, event in activity.items()
                if day <= today.isoformat()
                and not event.get("sent")
                and event.get("next_attempt", 0) <= time.time()
            }
        for day, event in pending.items():
            if self._stopping or is_telemetry_opted_out(self.directory):
                return
            payload = event.get("payload")
            if payload is None:
                payload = {
                    **get_environment_info(),
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
                with telemetry_marker(self.directory) as data:
                    data["daily_activity"][day]["payload"] = payload
            if self._stopping or is_telemetry_opted_out(self.directory):
                return
            success = _upload_telemetry_sync(payload)
            attempts = event.get("attempts", 0) + 1
            delay = min(60 * 2 ** min(attempts - 1, 10), 3600)
            with telemetry_marker(self.directory) as data:
                if success:
                    data["daily_activity"][day] = {"sent": True}
                else:
                    data["daily_activity"][day] = {
                        "payload": payload,
                        "attempts": attempts,
                        "next_attempt": time.time()
                        + delay
                        + random.uniform(0, delay / 4),
                    }


def start_daily_telemetry() -> DailyTelemetry:
    """Attach the single Runtime sender to the application lifespan."""
    global _service  # pylint: disable=global-statement
    _service = DailyTelemetry(WORKING_DIR)
    _service.start()
    return _service


async def record_agent_activity() -> None:
    """Record Agent execution regardless of its trigger or channel."""
    if _service is not None:
        await _service.record()
