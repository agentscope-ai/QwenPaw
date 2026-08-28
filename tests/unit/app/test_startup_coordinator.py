# -*- coding: utf-8 -*-
"""Tests for shared startup phase supervision."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app.startup_coordinator import StartupCoordinator


def test_phase_transitions_are_exposed() -> None:
    coordinator = StartupCoordinator(("api_ready",))

    coordinator.mark_running("api_ready")
    coordinator.mark_ready("api_ready")

    phase = coordinator.snapshot()["phases"]["api_ready"]
    assert phase["status"] == "ready"
    assert phase["started_ms"] is not None
    assert phase["finished_ms"] is not None
    assert phase["error"] is None


def test_terminal_phase_does_not_regress() -> None:
    coordinator = StartupCoordinator(("chat_core_ready",))

    coordinator.mark_ready("chat_core_ready")
    coordinator.mark_failed("chat_core_ready", "late worker failure")

    phase = coordinator.snapshot()["phases"]["chat_core_ready"]
    assert phase["status"] == "ready"
    assert phase["error"] is None


@pytest.mark.asyncio
async def test_worker_failure_is_isolated() -> None:
    coordinator = StartupCoordinator(("plugins_ready",))

    async def fail() -> None:
        raise RuntimeError("plugin failed")

    task = coordinator.start_worker("plugins_ready", fail)
    await task

    phase = coordinator.snapshot()["phases"]["plugins_ready"]
    assert phase["status"] == "failed"
    assert phase["error"] == "plugin failed"


@pytest.mark.asyncio
async def test_stop_cancels_active_workers() -> None:
    coordinator = StartupCoordinator(("browser_ready",))
    started = asyncio.Event()

    async def wait_forever() -> None:
        started.set()
        await asyncio.Event().wait()

    task = coordinator.start_worker("browser_ready", wait_forever)
    await started.wait()
    await coordinator.stop()

    assert task.cancelled()
