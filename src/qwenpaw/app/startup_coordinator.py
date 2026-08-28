# -*- coding: utf-8 -*-
"""Readiness and failure tracking for application startup phases."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any


_PENDING = "pending"
_RUNNING = "running"
_READY = "ready"
_FAILED = "failed"


@dataclass
class StartupPhase:
    """Mutable state for one independently observable startup phase."""

    status: str = _PENDING
    started_ms: float | None = None
    finished_ms: float | None = None
    error: str | None = None


class StartupCoordinator:
    """Supervise startup tasks and publish monotonic readiness."""

    def __init__(self, phase_names: tuple[str, ...]) -> None:
        self._started_at = time.monotonic()
        self._phases = {
            phase_name: StartupPhase() for phase_name in phase_names
        }
        self._terminal_events = {
            phase_name: asyncio.Event() for phase_name in phase_names
        }
        self._tasks: set[asyncio.Task[Any]] = set()

    def mark_running(self, phase_name: str) -> None:
        """Mark a phase as running without resetting its timestamp."""
        phase = self._phase(phase_name)
        if phase.status in {_READY, _FAILED}:
            return
        phase.status = _RUNNING
        if phase.started_ms is None:
            phase.started_ms = self._elapsed_ms()

    def mark_ready(self, phase_name: str) -> None:
        """Mark a phase as ready."""
        phase = self._phase(phase_name)
        if phase.status == _FAILED:
            return
        if phase.started_ms is None:
            phase.started_ms = self._elapsed_ms()
        phase.status = _READY
        phase.finished_ms = self._elapsed_ms()
        phase.error = None
        self._terminal_events[phase_name].set()

    def mark_failed(self, phase_name: str, error: BaseException | str) -> None:
        """Mark a phase as failed without raising into sibling workers."""
        phase = self._phase(phase_name)
        if phase.status == _READY:
            return
        if phase.started_ms is None:
            phase.started_ms = self._elapsed_ms()
        phase.status = _FAILED
        phase.finished_ms = self._elapsed_ms()
        phase.error = str(error)
        self._terminal_events[phase_name].set()

    async def wait_for_terminal(self, phase_name: str) -> StartupPhase:
        """Wait until one phase is ready or failed, then return its state."""
        self._phase(phase_name)
        await self._terminal_events[phase_name].wait()
        return self._phase(phase_name)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of every startup phase."""
        return {
            "elapsed_ms": round(self._elapsed_ms(), 3),
            "phases": {
                phase_name: asdict(phase)
                for phase_name, phase in self._phases.items()
            },
        }

    def start_worker(
        self,
        phase_name: str,
        worker: Callable[[], Awaitable[None]],
    ) -> asyncio.Task[Any]:
        """Start and supervise one readiness worker."""

        async def _run() -> None:
            self.mark_running(phase_name)
            try:
                await worker()
            except Exception as exc:  # noqa: BLE001 - worker isolation
                self.mark_failed(phase_name, exc)
            else:
                self.mark_ready(phase_name)

        task = asyncio.create_task(
            _run(),
            name=f"startup:{phase_name}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def stop(self) -> None:
        """Cancel and retrieve every active worker task."""
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _phase(self, phase_name: str) -> StartupPhase:
        try:
            return self._phases[phase_name]
        except KeyError as exc:
            raise ValueError(
                f"Unknown startup phase: {phase_name}",
            ) from exc

    def _elapsed_ms(self) -> float:
        return (time.monotonic() - self._started_at) * 1000
