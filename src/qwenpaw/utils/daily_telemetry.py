# -*- coding: utf-8 -*-
"""Best-effort daily Runtime telemetry in a detached sender thread."""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..constant import EnvVarLoader, WORKING_DIR
from .telemetry import (
    TELEMETRY_ENDPOINT,
    get_environment_info,
    is_telemetry_opted_out,
    telemetry_marker,
)

logger = logging.getLogger(__name__)
_service: DailyTelemetry | None = None


async def _upload_daily(payload: dict[str, Any]) -> bool:
    """Run only in the sender thread, with one budget for all attempts."""
    try:
        async with asyncio.timeout(5):
            async with httpx.AsyncClient(timeout=2.0) as client:
                for _ in range(3):
                    try:
                        async with asyncio.timeout(2):
                            async with client.stream(
                                "POST",
                                TELEMETRY_ENDPOINT,
                                json=payload,
                            ) as response:
                                if response.status_code in (200, 201, 204):
                                    return True
                    except (httpx.HTTPError, TimeoutError):
                        pass
    except (httpx.HTTPError, TimeoutError):
        pass
    return False


class DailyTelemetry:
    """Deduplicate in memory and on disk; never wait for the sender."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()
        self._last_queued_day = ""
        self._environment: dict[str, Any] | None = None
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Wait for Agent activity in one dedicated daemon thread."""
        self._thread = threading.Thread(
            target=self._run,
            name="qwenpaw-daily-telemetry",
            daemon=True,
        )
        self._thread.start()

    async def close(self) -> None:
        """Signal shutdown without joining or waiting for network work."""
        self._stopping = True
        self._queue.put(None)

    async def record(self, day: str | None = None) -> bool:
        """Queue once per UTC day with no disk I/O or suspension points."""
        day = day or datetime.now(timezone.utc).date().isoformat()
        if self._stopping or day <= self._last_queued_day:
            return False
        self._last_queued_day = day
        self._queue.put(day)
        return True

    def _run(self) -> None:
        while not self._stopping:
            day = self._queue.get()
            if day is None or self._stopping:
                return
            try:
                self._send(day)
            except Exception:
                logger.debug("Daily telemetry failed", exc_info=True)

    def _send(self, day: str) -> None:
        """Claim today's attempt before probing or uploading; never replay."""
        if is_telemetry_opted_out(self.directory):
            return
        with telemetry_marker(self.directory) as data:
            if day <= data.get("daily_attempt_date", ""):
                return
            runtime_id = data.setdefault(
                "telemetry_runtime_id",
                str(uuid.uuid4()),
            )
            data["daily_attempt_date"] = day
        if self._environment is None:
            self._environment = get_environment_info()
        payload = {
            **self._environment,
            "schema_version": 2,
            "event_type": "runtime_active",
            "telemetry_runtime_id": runtime_id,
            "install_id": runtime_id,
            "activity_date": day,
            "deployment_mode": (
                "hub"
                if EnvVarLoader.get_str("QWENPAW_RUNTIME_ID")
                else "standalone"
            ),
        }
        if self._stopping or is_telemetry_opted_out(self.directory):
            return
        # This private event loop belongs to the daemon, not the app loop.
        if not asyncio.run(_upload_daily(payload)):
            logger.debug("Daily telemetry abandoned for %s", day)


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
